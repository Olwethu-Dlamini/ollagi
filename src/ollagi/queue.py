"""The overnight queue: tasks that run one at a time while I am away (docs/decisions/0012).

A task is a project folder plus a prompt. When its turn comes, it is started as an ordinary ollagi
session running `claude "<prompt>"`, so it can be watched and answered from the phone like any other.

Life of a task:

    queued -> running -> done            Claude worked, then finished its turn
                      -> waiting         Claude is asking something; the queue holds until answered
                      -> limited         the screen says a usage limit was hit; the queue pauses
                      -> failed          the session ended, or Claude never started working
    queued -> cancelled

Tasks live in a small SQLite database (sqlite3 is in Python's standard library): one file, no
server, and it survives restarts of ollagi.
"""

import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PATH = Path.home() / ".local" / "share" / "ollagi" / "queue.db"
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


class Store:
    def __init__(self, path: Path = DEFAULT_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the web server and the queue thread share this connection;
        # every method is short and sqlite serialises the writes.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def add(self, directory: str, prompt: str) -> Task:
        if not prompt.strip():
            raise ValueError("a task needs a prompt")
        if not Path(directory).is_dir():
            raise ValueError(f"not a folder: {directory}")
        cur = self.db.execute("INSERT INTO tasks (directory, prompt, created) VALUES (?, ?, ?)",
                              (directory, prompt.strip(), time.time()))
        self.db.commit()
        return self.get(cur.lastrowid)

    def get(self, task_id: int) -> Task:
        row = self.db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return _task(row)

    def all(self) -> list[Task]:
        return [_task(r) for r in self.db.execute("SELECT * FROM tasks ORDER BY id")]

    def next_queued(self) -> Task | None:
        row = self.db.execute("SELECT * FROM tasks WHERE status = 'queued' ORDER BY id LIMIT 1").fetchone()
        return _task(row) if row else None

    def active(self) -> Task | None:
        row = self.db.execute("SELECT * FROM tasks WHERE status IN ('running', 'waiting') ORDER BY id LIMIT 1").fetchone()
        return _task(row) if row else None

    def update(self, task_id: int, **fields) -> Task:
        allowed = {"status", "session", "note", "started", "finished", "seen_working"}
        if not fields or set(fields) - allowed:
            raise ValueError(f"can only update {sorted(allowed)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", (*fields.values(), task_id))
        self.db.commit()
        return self.get(task_id)

    def cancel(self, task_id: int) -> Task:
        task = self.get(task_id)
        if task.status != "queued":
            raise ValueError(f"task {task_id} is {task.status}; only queued tasks can be cancelled")
        return self.update(task_id, status="cancelled", finished=time.time())

    def paused(self) -> bool:
        row = self.db.execute("SELECT value FROM settings WHERE key = 'paused'").fetchone()
        return bool(row and row["value"] == "1")

    def set_paused(self, paused: bool, reason: str = "") -> None:
        self.db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('paused', ?)", ("1" if paused else "0",))
        self.db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('pause_reason', ?)", (reason,))
        self.db.commit()

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
