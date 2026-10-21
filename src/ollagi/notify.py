"""What is worth a notification on the phone, and getting it there (docs/decisions/0024).

Four things send one:

- a session starts asking something (a permission, a question, a plan to approve): "api needs you";
- a session's turn ends after it was working: "api finished";
- the overnight queue reports a task done, waiting, failed or stopped by a usage limit;
- the RAM watcher pauses, stops or resumes a session.

Sessions are read every few seconds by the server, the same way the page reads them. A state only
counts once it has been read twice in a row: between two tool calls the spinner can vanish for a
moment while an older "✻ Worked for 3s" line is still on screen, and that one read must not buzz the
phone. A session seen for the first time (for example when the server starts) is not news.

Each notice has a tag: the phone shows the newest notice per tag, so a session never piles up more
than one. The phones to notify are the browser subscriptions the page registered (SQLite, next to
the queue's database). Sending happens on its own thread, so a slow push service never holds up the
RAM watcher or the queue.
"""

import queue as queues
import re
import sqlite3
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path

from ollagi import webpush

DATA = Path.home() / ".local" / "share" / "ollagi"
DEFAULT_DB = DATA / "push.db"
DEFAULT_KEY = DATA / "push" / "vapid.pem"
SETTLE_READS = 2
EVERY_SECONDS = 5
MAX_BODY = 500  # a notification shows two or three lines; the rest is on the page
QUEUE_SESSION = re.compile(r"^q\d+$")
QUEUE_WORDS = (" done", "waiting for you", "usage limit", "failed", "could not start", "queue error")

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
    endpoint TEXT PRIMARY KEY,
    p256dh   TEXT NOT NULL,
    auth     TEXT NOT NULL,
    created  REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Notice:
    title: str
    body: str
    tag: str  # the phone keeps only the newest notice per tag
    url: str  # where the page opens when the notice is tapped


def session_notice(name: str, before: str, now: str, question: str | None) -> Notice | None:
    url = f"/?session={name}"
    if now == "needs_you":
        return Notice(f"{name} needs you", question or "Claude is asking something.", f"session-{name}", url)
    if now == "done" and before == "working":
        return Notice(f"{name} finished", "Claude's turn ended.", f"session-{name}", url)
    return None


class SessionWatch:
    """Turns repeated readings of every session's state into notices about changes."""

    def __init__(self):
        self.last: dict[str, tuple[str, int]] = {}  # name -> (state last read, reads in a row)
        self.settled: dict[str, str] = {}           # name -> the state that counts

    def update(self, readings: dict[str, tuple[str, str | None]]) -> list[Notice]:
        """`readings`: name -> (state, question) for every session now."""
        for gone in set(self.last) - set(readings):
            self.last.pop(gone)
            self.settled.pop(gone, None)
        found = []
        for name, (state, question) in readings.items():
            previous, count = self.last.get(name, (None, 0))
            count = count + 1 if state == previous else 1
            self.last[name] = (state, count)
            if count < SETTLE_READS or self.settled.get(name) == state:
                continue
            before = self.settled.get(name)
            self.settled[name] = state
            if before is None or QUEUE_SESSION.match(name):
                continue
            notice = session_notice(name, before, state, question)
            if notice:
                found.append(notice)
        return found


def queue_notice(text: str) -> Notice | None:
    if any(word in text for word in QUEUE_WORDS):
        return Notice("Queue", text, "queue", "/?view=queue")
    return None


def watcher_notice(kind: str, name: str) -> Notice:
    body = {"freeze": f"Paused {name} to free memory.",
            "stop": f"Stopped {name} to free memory.",
            "thaw": f"Memory is back; {name} continues."}[kind]
    return Notice("Memory low", body, "watcher", f"/?session={name}")


class Subscribers:
    """The phones (browser subscriptions) to notify."""

    def __init__(self, path: Path = DEFAULT_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        path.chmod(0o600)  # each row holds a phone's secret; only my user reads it

    def add(self, sub: webpush.Subscription) -> None:
        if not webpush.known_push_service(sub.endpoint):
            raise ValueError("not a browser push service address")
        try:
            public, auth = webpush.unb64(sub.p256dh), webpush.unb64(sub.auth)
        except ValueError as error:
            raise ValueError("keys are not base64url") from error
        if len(public) != 65 or public[0] != 4 or len(auth) != 16:
            raise ValueError("keys are not a P-256 public key and a 16-byte secret")
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO subscriptions VALUES (?, ?, ?, ?)",
                            (sub.endpoint, sub.p256dh, sub.auth, time.time()))
            self.db.commit()

    def remove(self, endpoint: str) -> bool:
        with self.lock:
            removed = self.db.execute("DELETE FROM subscriptions WHERE endpoint = ?", (endpoint,)).rowcount
            self.db.commit()
        return removed > 0

    def all(self) -> list[webpush.Subscription]:
        with self.lock:
            rows = self.db.execute("SELECT endpoint, p256dh, auth FROM subscriptions ORDER BY created").fetchall()
        return [webpush.Subscription(*row) for row in rows]


class Notifier:
    def __init__(self, subscribers: Subscribers, key, send=webpush.send):
        self.subscribers, self.key, self.send = subscribers, key, send
        self.events: deque = deque(maxlen=20)
        self.outbox: queues.Queue = queues.Queue()

    def deliver(self, notice: Notice) -> dict:
        """Send now, to every phone. A phone its push service has forgotten is dropped."""
        message = {**asdict(notice), "body": notice.body[:MAX_BODY]}
        sent, failed = 0, []
        for sub in self.subscribers.all():
            try:
                self.send(sub, message, self.key, now=time.time())
                sent += 1
            except webpush.Gone:
                self.subscribers.remove(sub.endpoint)
                self.note("a phone unsubscribed (its push service forgot it); removed")
            except (OSError, RuntimeError, ValueError) as error:
                failed.append(str(error))
                self.note(f"could not send \"{notice.title}\": {error}")
        if sent:
            self.note(f"sent \"{notice.title}\" to {sent} phone{'s' if sent > 1 else ''}")
        return {"sent": sent, "failed": failed}

    def notify(self, notice: Notice | None) -> None:
        """Send later, on the sending thread (see run_sender)."""
        if notice is not None:
            self.outbox.put(notice)

    def note(self, text: str) -> None:
        self.events.append({"time": time.time(), "text": text})


def run_sender(notifier: Notifier, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            notice = notifier.outbox.get(timeout=1)
        except queues.Empty:
            continue
        notifier.deliver(notice)


def watch_sessions(read, notifier: Notifier, stop: threading.Event, every: float = EVERY_SECONDS) -> None:
    """`read()` returns name -> (state, question) for every session, as the page shows them."""
    watch = SessionWatch()
    while not stop.wait(every):
        try:
            for notice in watch.update(read()):
                notifier.notify(notice)
        except Exception as error:  # a session ending mid-read must not end the watching
            notifier.note(f"could not read the sessions: {error}")
