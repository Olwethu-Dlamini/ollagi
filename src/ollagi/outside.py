"""Claude sessions started outside ollagi (in a plain terminal window): see them, and take them over.

Such a session cannot be read or typed into from outside its window (decision 0015 explains why),
but Claude Code itself keeps two files that ollagi can read (docs/decisions/0016):

  ~/.claude/sessions/<pid>.json           one per running Claude: its conversation id, folder,
                                          name and whether it is "busy" or "idle"
  ~/.claude/projects/<folder>/<id>.jsonl  the conversation so far, one JSON entry per line, the
                                          file `claude --resume <id>` reads

These are Claude Code's internal files (seen in version 2.1.280), not a published format, so every
field is read defensively and a file that does not parse is skipped.

Taking over: ollagi ends Claude in that window and reopens the same conversation as an ollagi
session (`claude --resume <id>`), which can then be watched and answered from the phone. Only an
idle session can be taken over, so no work in progress is cut off.
"""

import json
import os
import re
import signal
import time
from dataclasses import dataclass
from pathlib import Path

CLAUDE_HOME = Path.home() / ".claude"
TAIL_BYTES = 400_000  # a long conversation's file is many MB; the last 400 kB holds the recent part


@dataclass(frozen=True)
class OutsideSession:
    pid: int
    session_id: str
    name: str
    cwd: str
    status: str  # "busy" or "idle", as Claude Code reports it
    started: float  # seconds
    updated: float


@dataclass(frozen=True)
class Item:
    role: str  # "you", "claude", "tool" or "event"
    text: str


def _tag(name: str, text: str) -> str | None:
    """The text inside <name>...</name>, or None when the tag is not there."""
    found = re.search(rf"<{name}>(.*?)</{name}>", text, re.DOTALL)
    return found.group(1).strip() if found else None


def _first_line(text: str, limit: int = 160) -> str:
    return text.strip().splitlines()[0][:limit] if text.strip() else ""


def user_item(text: str) -> Item | None:
    """A typed line as a person would read it. Claude Code also stores its own bookkeeping as
    "user" lines wrapped in tags: a slash command, a `!` shell line and their output, background
    task notices. Those become short lines; notices nobody typed are left out."""
    text = text.strip()
    if text.startswith("<task-notification>"):
        return None
    command = _tag("command-name", text)
    if command is not None:
        return Item("you", f"{command} {_tag('command-args', text) or ''}".strip())
    shell = _tag("bash-input", text)
    if shell is not None:
        return Item("you", f"! {shell}")
    for output in ("local-command-stdout", "bash-stdout"):
        printed = _tag(output, text)
        if printed is not None:
            return Item("tool", _first_line(printed)) if printed else None
    text = re.sub(r"<pasted_content[^>]*>.*?</pasted_content[^>]*>", "[pasted text]", text, flags=re.DOTALL)
    return Item("you", text) if text else None


def process_start(pid: int, proc: Path = Path("/proc")) -> str | None:
    """Field 22 of /proc/<pid>/stat: when the process started (in clock ticks since boot)."""
    try:
        text = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    return text[text.rindex(")") + 2:].split()[19]


def list_sessions(claude_home: Path = CLAUDE_HOME, proc: Path = Path("/proc")) -> list[OutsideSession]:
    found = []
    for file in sorted((claude_home / "sessions").glob("*.json")):
        try:
            data = json.loads(file.read_text())
            pid = int(data["pid"])
        except (OSError, ValueError, KeyError):
            continue
        # A pid number is reused after a process ends, so also compare the start time Claude
        # recorded with the process's real one. Different means this file is stale.
        if data.get("kind") != "interactive" or process_start(pid, proc) != str(data.get("procStart")):
            continue
        # `claude -p` (a one-shot answer, such as ollagi's summaries) is marked "interactive" too;
        # only its entrypoint, "sdk-cli", tells it apart from a session in a terminal.
        if data.get("entrypoint") == "sdk-cli":
            continue
        found.append(OutsideSession(
            pid=pid,
            session_id=str(data.get("sessionId", "")),
            name=str(data.get("name") or f"pid-{pid}"),
            cwd=str(data.get("cwd", "")),
            status=str(data.get("status", "unknown")),
            started=float(data.get("startedAt", 0)) / 1000,
            updated=float(data.get("updatedAt", 0)) / 1000,
        ))
    return found


def transcript_path(session_id: str, claude_home: Path = CLAUDE_HOME) -> Path | None:
    if not session_id or "/" in session_id:
        return None
    return next((claude_home / "projects").glob(f"*/{session_id}.jsonl"), None)


def read_tail(path: Path, max_bytes: int = TAIL_BYTES) -> list[str]:
    with path.open("rb") as f:
        size = f.seek(0, os.SEEK_END)
        f.seek(max(0, size - max_bytes))
        lines = f.read().decode("utf-8", "replace").splitlines()
    return lines[1:] if size > max_bytes else lines  # the first line may be cut in half


def parse_conversation(lines: list[str], limit: int = 40) -> tuple[str | None, list[Item]]:
    """The conversation's title and its last `limit` readable items."""
    title, items = None, []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") == "ai-title" and entry.get("aiTitle"):
            title = entry["aiTitle"]
        if entry.get("isSidechain"):  # a subagent's own conversation
            continue
        if entry.get("isMeta"):  # context Claude Code adds by itself, never typed
            continue
        message = entry.get("message") or {}
        content = message.get("content")
        if entry.get("type") == "user" and isinstance(content, str) and content.strip():
            item = user_item(content)
            if item:
                items.append(item)
        elif entry.get("type") == "user" and isinstance(content, list):
            for block in content:  # tool results are skipped; an interruption is worth a line
                if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").startswith("[Request interrupted"):
                    items.append(Item("event", block["text"].strip("[] ")))
        elif entry.get("type") == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text", "").strip():
                    items.append(Item("claude", block["text"].strip()))
                elif block.get("type") == "tool_use":
                    items.append(Item("tool", tool_summary(block)))
    return title, items[-limit:]


def tool_summary(block: dict) -> str:
    args = block.get("input") or {}
    detail = args.get("description") or args.get("command") or args.get("file_path") or args.get("pattern") or ""
    first_line = str(detail).splitlines()[0][:160] if detail else ""
    return f"{block.get('name', 'tool')}: {first_line}" if first_line else str(block.get("name", "tool"))


def end_process(pid: int, wait: float = 10.0, signal_number: int = signal.SIGTERM) -> bool:
    """Ask a process to end (SIGTERM lets Claude save and exit cleanly); True once it is gone."""
    try:
        os.kill(pid, signal_number)
    except ProcessLookupError:
        return True
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not Path(f"/proc/{pid}").exists():
            return True
        time.sleep(0.2)
    return False
