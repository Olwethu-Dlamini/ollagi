"""A folder's recent omp conversations, to resume one from the page (docs/decisions/0037).

omp keeps every conversation as one JSON-lines file under ~/.omp/agent/sessions/<folder>/, named
<start time>_<id>.jsonl. Its first lines say what the file is (seen in omp 18.12):

    {"type": "title", "title": "Consolidate agent rules and memory files", ...}
    {"type": "session", "id": "01a1772c-...", "cwd": "/tmp", ...}

The folder name is omp's own encoding of the path; rather than copy that rule, the files are matched by
the `cwd` they record, which is exact. Only the first few lines of each file are read.
"""

import json
from pathlib import Path

from ollagi.outside import Conversation

SESSIONS_ROOT = Path.home() / ".omp" / "agent" / "sessions"
HEADER_LINES = 5


def header(path: Path) -> tuple[str | None, str | None, str | None]:
    """(cwd, conversation id, title) from the top of a conversation file; None where missing."""
    cwd = conversation_id = title = None
    with path.open(encoding="utf-8", errors="replace") as fh:
        for _ in range(HEADER_LINES):
            line = fh.readline()
            if not line:
                break
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") == "title" and isinstance(entry.get("title"), str):
                title = entry["title"]
            elif entry.get("type") == "session":
                cwd, conversation_id = entry.get("cwd"), entry.get("id")
    return cwd, conversation_id, title


def recent(directory: str, root: Path = SESSIONS_ROOT, limit: int = 8, leave_out: frozenset[str] = frozenset()) -> list[Conversation]:
    """The folder's newest conversations, newest first, without the ids in `leave_out` (conversations a
    running session has open: two omp processes writing one file would corrupt it)."""
    if not root.is_dir():
        return []
    files = sorted((f for f in root.glob("*/*.jsonl") if f.stat().st_size > 0), key=lambda f: f.stat().st_mtime, reverse=True)
    want = Path(directory)
    found = []
    for path in files:
        try:
            cwd, conversation_id, title = header(path)
        except OSError:
            continue
        if not cwd or not conversation_id or Path(cwd) != want or conversation_id in leave_out:
            continue
        found.append(Conversation(conversation_id, title or "(untitled)", path.stat().st_mtime))
        if len(found) == limit:
            break
    return found
