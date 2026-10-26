"""Read an omp session's state from the file its hook writes (docs/decisions/0036).

A Claude session's state is read from its screen (claude_screen.py). omp has hooks, so
deploy/omp/ollagi-state.ts writes the state as it changes, to one small file per session:

    $XDG_RUNTIME_DIR/ollagi/<session>.json   {"state", "question", "options", "updated", "pid"}

$XDG_RUNTIME_DIR is a folder in RAM that only I can read (/run/user/<uid>), cleared at logout, which
suits a state that only matters while the session runs. The hook knows the session's name because
ollagi starts every session with OLLAGI_SESSION=<name> in its environment (sessions.start_command).

The answer has the same shape as claude_screen.read(), so the page, the notifier and the queue do not
need to know which agent a session runs.
"""

import json
import os
from pathlib import Path

from ollagi.claude_screen import Option, Reading

STATES = {"idle", "working", "needs_you", "done"}


def runtime_dir() -> Path:
    """Where the hook writes; the hook uses the same rule (XDG_RUNTIME_DIR, else a /tmp folder)."""
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/ollagi-{os.getuid()}"
    return Path(base) / "ollagi"


def read(name: str, folder: Path | None = None) -> Reading:
    """The session's last reported state. No file yet (omp still starting, or the hook is not
    installed) or a file that cannot be read reads as "unknown", never as a guess."""
    try:
        data = json.loads(((folder or runtime_dir()) / f"{name}.json").read_text())
    except (FileNotFoundError, ValueError):
        return Reading("unknown")
    state = data.get("state")
    if state not in STATES:
        return Reading("unknown")
    labels = [label for label in data.get("options") or [] if isinstance(label, str)]
    question = data.get("question") if isinstance(data.get("question"), str) else None
    return Reading(state, question=question, options=[Option(i, label) for i, label in enumerate(labels, start=1)])


def open_conversations(folder: Path | None = None) -> frozenset[str]:
    """Conversation ids that running omp sessions have open, from their state files (the hook writes
    the id it was started or resumed with). A resume list must leave these out (docs/decisions/0037)."""
    found = set()
    for path in (folder or runtime_dir()).glob("*.json"):
        try:
            conversation = json.loads(path.read_text()).get("conversation")
        except (OSError, ValueError):
            continue
        if isinstance(conversation, str) and conversation:
            found.add(conversation)
    return frozenset(found)
