"""A Slack outbox: ollagi drafts, I approve each message, then it is sent (docs/decisions/0014).

The standing rule for my Slack is: nothing is posted in my name until I have seen the exact text and
said OK, for every single message. So ollagi never posts on its own. It keeps drafts; a draft is
sent only when I press Send on that draft, and the server checks that the text I confirmed is
exactly the text stored. A sent draft can never be sent again.

Sending goes through the Slack helper already on this machine, ~/slack.sh, which holds the token,
refreshes it when it expires, and turns "@Name" into real mentions:

    slack.sh preview <text|->                        who a new post would notify (sends nothing)
    slack.sh preview <#channel> <thread-ts> <text|-> same, for a reply in a thread
    slack.sh post    <#channel> <text|->             post (text from stdin with "-")
    slack.sh reply   <#channel> <thread-ts> <text|-> reply in a thread
"""

import sqlite3
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ollagi.queue import DEFAULT_PATH, locked

SLACK_HELPER = Path.home() / "slack.sh"

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    channel   TEXT NOT NULL,
    thread_ts TEXT,
    text      TEXT NOT NULL,
    status    TEXT NOT NULL DEFAULT 'draft',
    source    TEXT NOT NULL DEFAULT 'me',
    created   REAL NOT NULL,
    sent_at   REAL,
    result    TEXT
);
"""

Run = Callable[[Sequence[str], str], subprocess.CompletedProcess]


def run_helper(argv: Sequence[str], stdin: str) -> subprocess.CompletedProcess:
    return subprocess.run(list(argv), input=stdin, capture_output=True, text=True, timeout=60)


@dataclass(frozen=True)
class Draft:
    id: int
    channel: str
    thread_ts: str | None
    text: str
    status: str  # draft, sent, discarded
    source: str  # "me" when written on the page, or what made it (e.g. "queue task 3")
    created: float
    sent_at: float | None
    result: str | None


class Outbox:
    def __init__(self, path: Path = DEFAULT_PATH, helper: Path = SLACK_HELPER, run: Run = run_helper):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self.helper, self.run = str(helper), run

    @locked
    def add(self, channel: str, text: str, thread_ts: str | None = None, source: str = "me") -> Draft:
        if not channel.strip() or not text.strip():
            raise ValueError("a draft needs a channel and some text")
        cur = self.db.execute(
            "INSERT INTO drafts (channel, thread_ts, text, source, created) VALUES (?, ?, ?, ?, ?)",
            (channel.strip(), (thread_ts or "").strip() or None, text, source, time.time()))
        self.db.commit()
        return self.get(cur.lastrowid)

    @locked
    def get(self, draft_id: int) -> Draft:
        row = self.db.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return Draft(**dict(row))

    @locked
    def all(self) -> list[Draft]:
        return [Draft(**dict(r)) for r in self.db.execute("SELECT * FROM drafts ORDER BY id DESC")]

    @locked
    def edit(self, draft_id: int, text: str) -> Draft:
        self._still_a_draft(draft_id)
        self.db.execute("UPDATE drafts SET text = ? WHERE id = ?", (text, draft_id))
        self.db.commit()
        return self.get(draft_id)

    @locked
    def discard(self, draft_id: int) -> Draft:
        self._still_a_draft(draft_id)
        self.db.execute("UPDATE drafts SET status = 'discarded' WHERE id = ?", (draft_id,))
        self.db.commit()
        return self.get(draft_id)

    def preview(self, draft_id: int) -> str:
        """Ask slack.sh who this message would notify. Sends nothing."""
        d = self.get(draft_id)
        args = [self.helper, "preview", d.channel, d.thread_ts, "-"] if d.thread_ts else [self.helper, "preview", "-"]
        result = self.run(args, d.text)
        lines = (result.stdout + result.stderr).strip().splitlines()
        return next((line for line in reversed(lines) if "notifies" in line), lines[-1] if lines else "")

    @locked
    def send(self, draft_id: int, confirmed_text: str) -> Draft:
        """Send one draft, only if the text I confirmed is exactly the stored text."""
        d = self._still_a_draft(draft_id)
        if confirmed_text != d.text:
            raise ValueError("the confirmed text is not the draft's text; nothing was sent")
        args = ([self.helper, "reply", d.channel, d.thread_ts, "-"] if d.thread_ts
                else [self.helper, "post", d.channel, "-"])
        result = self.run(args, d.text)
        if result.returncode != 0:
            raise RuntimeError(f"slack.sh refused: {(result.stderr or result.stdout).strip()}")
        self.db.execute("UPDATE drafts SET status = 'sent', sent_at = ?, result = ? WHERE id = ?",
                        (time.time(), result.stdout.strip(), draft_id))
        self.db.commit()
        return self.get(draft_id)

    def _still_a_draft(self, draft_id: int) -> Draft:
        d = self.get(draft_id)
        if d.status != "draft":
            raise ValueError(f"draft {draft_id} is already {d.status}")
        return d
