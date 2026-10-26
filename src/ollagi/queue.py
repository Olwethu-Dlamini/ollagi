"""The overnight queue: tasks that run one at a time while I am away (docs/decisions/0012).

A task is a project folder plus a prompt. When its turn comes, it is started as an ordinary ollagi
session running the folder's agent with the prompt, `claude "<prompt>"` or `omp "<prompt>"`
(docs/decisions/0035), so it can be watched and answered from the phone like any other.

Life of a task:

    queued -> running -> done            the agent finished its turn (final screen saved, session stopped)
                      -> waiting         the agent is asking something; the queue holds until answered
                      -> limited         the screen says a usage limit was hit; the queue pauses
                      -> failed          the session ended, or the agent never started working
    queued -> cancelled

Tasks live in a small SQLite database (sqlite3 is in Python's standard library): one file, no
server, and it survives restarts of ollagi.
"""

import re
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ollagi import agents, claude_screen, omp_state

DEFAULT_PATH = Path.home() / ".local" / "share" / "ollagi" / "queue.db"
RESULTS_DIR = Path.home() / ".local" / "share" / "ollagi" / "results"
ACTIVE = ("running", "waiting")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    directory TEXT NOT NULL,
    prompt    TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'queued',
    session   TEXT,
    note      TEXT,
    created   REAL NOT NULL,
    started   REAL,
    finished  REAL,
    seen_working INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True)
class Task:
    id: int
    directory: str
    prompt: str
    status: str
    session: str | None
    note: str | None
    created: float
    started: float | None
    finished: float | None
    seen_working: bool


def locked(method):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    wrapper.__name__, wrapper.__doc__ = method.__name__, method.__doc__
    return wrapper


class Store:
    def __init__(self, path: Path = DEFAULT_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        # The web server and the queue thread share this connection, so every use of it takes the
        # lock: one statement at a time, never two threads inside sqlite at once.
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    @locked
    def add(self, directory: str, prompt: str) -> Task:
        if not prompt.strip():
            raise ValueError("a task needs a prompt")
        if not Path(directory).is_dir():
            raise ValueError(f"not a folder: {directory}")
        cur = self.db.execute("INSERT INTO tasks (directory, prompt, created) VALUES (?, ?, ?)",
                              (directory, prompt.strip(), time.time()))
        self.db.commit()
        return self.get(cur.lastrowid)

    @locked
    def get(self, task_id: int) -> Task:
        row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return _task(row)

    @locked
    def all(self) -> list[Task]:
        return [_task(r) for r in self.db.execute("SELECT * FROM tasks ORDER BY id")]

    @locked
    def next_queued(self) -> Task | None:
        row = self.db.execute("SELECT * FROM tasks WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
        return _task(row) if row else None

    @locked
    def active(self) -> Task | None:
        row = self.db.execute("SELECT * FROM tasks WHERE status IN ('running', 'waiting') ORDER BY id LIMIT 1").fetchone()
        return _task(row) if row else None

    @locked
    def update(self, task_id: int, **fields) -> Task:
        allowed = {"status", "session", "note", "started", "finished", "seen_working"}
        if not fields or set(fields) - allowed:
            raise ValueError(f"can only update {sorted(allowed)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", (*fields.values(), task_id))
        self.db.commit()
        return self.get(task_id)

    @locked
    def cancel(self, task_id: int) -> Task:
        task = self.get(task_id)
        if task.status != "queued":
            raise ValueError(f"task {task_id} is {task.status}; only queued tasks can be cancelled")
        return self.update(task_id, status="cancelled", finished=time.time())

    @locked
    def paused(self) -> bool:
        row = self.db.execute("SELECT value FROM settings WHERE key = 'paused'").fetchone()
        return bool(row and row["value"] == "1")

    @locked
    def set_paused(self, paused: bool, reason: str = "") -> None:
        self.db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('paused', ?)", ("1" if paused else "0",))
        self.db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('pause_reason', ?)", (reason,))
        self.db.commit()

    @locked
    def pause_reason(self) -> str:
        row = self.db.execute("SELECT value FROM settings WHERE key = 'pause_reason'").fetchone()
        return row["value"] if row else ""


def _task(row: sqlite3.Row) -> Task:
    return Task(**{**dict(row), "seen_working": bool(row["seen_working"])})


# Claude Code's wording for a hit limit varies ("5-hour limit reached", "usage limit reached",
# "Your limit will reset at 5pm"), so match the common words, case-insensitive. NOT yet checked
# against a captured limit screen: when one is seen, add it to tests/fixtures and test on it.
LIMIT = re.compile(r"(usage|weekly|\d+-hour|session) limit (reached|hit)|limit will reset|limit reached\b", re.I)


def hit_limit(screen_text: str) -> bool:
    return bool(LIMIT.search(screen_text))


@dataclass
class Runner:
    """Decides, every few seconds, what the queue should do next. One task at a time.

    Everything outside the database is passed in, so tests can drive it with fakes:
      sessions_api  start, names, info, screen, scope_state, stop (normally ollagi.sessions)
      room          returns True when the budget rule and the RAM watcher allow a new session
      agent_for     the agent a task's folder runs (normally the config's choice, docs/decisions/0035)
      omp_states    an omp session's state from its hook's file (docs/decisions/0036)
    """

    store: Store
    sessions_api: object
    room: Callable[[], bool]
    agent_for: Callable[[str], agents.Agent] = lambda directory: agents.get(agents.DEFAULT)
    omp_states: Callable[[str], claude_screen.Reading] = omp_state.read
    results_dir: Path = RESULTS_DIR
    give_up_after: float = 300.0  # a task whose agent never starts working in 5 minutes has failed

    def step(self, now: float) -> str:
        """Do at most one thing; return what was done, in words (for the event log)."""
        task = self.store.active()
        if task:
            return self.follow(task, now)
        if self.store.paused():
            return ""
        task = self.store.next_queued()
        if task is None or not self.room():
            return ""
        return self.begin(task, now)

    def begin(self, task: Task, now: float) -> str:
        name = f"q{task.id}"
        try:
            self.sessions_api.start(name, task.directory, self.agent_for(task.directory).with_prompt(task.prompt))
        except (ValueError, RuntimeError) as error:
            self.store.update(task.id, status="failed", note=str(error), finished=now)
            return f"task {task.id} could not start: {error}"
        self.store.update(task.id, status="running", session=name, started=now)
        return f"task {task.id} started as session {name}"

    def follow(self, task: Task, now: float) -> str:
        name = task.session
        if name not in self.sessions_api.names():
            self.store.update(task.id, status="failed", note="the session ended", finished=now)
            return f"task {task.id} failed: its session ended"
        if self.sessions_api.scope_state(name)[0]:
            return ""  # frozen by the RAM watcher or by hand; nothing to read until it is thawed

        text = self.sessions_api.screen(name, lines=80)
        if hit_limit(text):
            self.store.update(task.id, status="limited", note="usage limit reached", finished=now)
            self.store.set_paused(True, f"usage limit reached during task {task.id}")
            return f"task {task.id} hit a usage limit; queue paused"

        # Claude's state is read from its screen; omp reports its own through a hook.
        reading = self.omp_states(name) if self.sessions_api.info(name).program == "omp" else claude_screen.read(text)
        if reading.state == "working":
            if task.status != "running" or not task.seen_working:
                self.store.update(task.id, status="running", seen_working=1)
            return ""
        if reading.state == "needs_you":
            if task.status != "waiting":
                self.store.update(task.id, status="waiting", note=reading.question)
                return f"task {task.id} is waiting for you: {reading.question}"
            return ""
        if reading.state == "done":
            # "done" means a finished-turn line is on screen, so the prompt was handled even if
            # the work was too quick for any check to see it "working".
            self.save_result(task, name)
            self.sessions_api.stop(name)
            self.store.update(task.id, status="done", note=None, finished=now)
            return f"task {task.id} done"
        # "is not None", not "or": a start time of 0 is a real time, but `0 or now` would skip it.
        started = task.started if task.started is not None else now
        if not task.seen_working and now - started > self.give_up_after:
            self.sessions_api.stop(name)
            self.store.update(task.id, status="failed", note="the agent never started working", finished=now)
            return f"task {task.id} failed: the agent never started working"
        return ""

    def save_result(self, task: Task, name: str) -> None:
        """Keep the final screen as plain text, so the outcome stays readable after the session ends."""
        self.results_dir.mkdir(parents=True, exist_ok=True)
        text = claude_screen.plain(self.sessions_api.screen(name, lines=2000))
        (self.results_dir / f"task-{task.id}.txt").write_text(f"{task.prompt}\n\n{text}\n")


def run_forever(runner: Runner, note: Callable[[str], None], stop: threading.Event, interval: float = 5.0) -> None:
    while not stop.is_set():
        try:
            said = runner.step(time.time())
            if said:
                note(said)
        except Exception as error:  # keep going; a silent dead queue is worse than a noisy one
            note(f"queue error: {error}")
        stop.wait(interval)
