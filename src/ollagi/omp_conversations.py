"""omp's conversations: a folder's recent ones to resume from the page (docs/decisions/0037), and the
omp sessions started in a terminal window outside ollagi (docs/decisions/0041).

omp keeps every conversation as one JSON-lines file under ~/.omp/agent/sessions/<folder>/, named
<start time>_<id>.jsonl. Its first lines say what the file is (seen in omp 18.12):

    {"type": "title", "title": "Consolidate agent rules and memory files", ...}
    {"type": "session", "id": "01a1772c-...", "cwd": "/tmp", ...}

The folder name is omp's own encoding of the path; rather than copy that rule, the files are matched by
the `cwd` they record, which is exact. Only the first few lines of each file are read.

omp writes no list of its running sessions (Claude Code does, see outside.py), but a running omp holds
its conversation file open, so /proc/<pid>/fd says which conversation each process has.
"""

import json
import os
from pathlib import Path

from ollagi.outside import Conversation, Item, OutsideSession, process_start

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


def _stat_fields(stat: str) -> tuple[int, str, int]:
    """(parent pid, process name, controlling terminal) from /proc/<pid>/stat. The name sits in
    brackets and may hold spaces; the terminal is 0 when the process has none."""
    name = stat[stat.index("(") + 1:stat.rindex(")")]
    rest = stat[stat.rindex(")") + 2:].split()
    return int(rest[1]), name, int(rest[4])


def _boot_time(proc: Path) -> float:
    for line in (proc / "stat").read_text().splitlines():
        if line.startswith("btime "):
            return float(line.split()[1])
    return 0.0


def _open_conversation(fd_folder: Path, root: Path) -> Path | None:
    """The main conversation file a process holds open; subagents' files sit one folder deeper."""
    for fd in fd_folder.iterdir():
        try:
            target = Path(os.readlink(fd))
        except OSError:
            continue
        if target.suffix == ".jsonl" and target.parent.parent == root:
            return target
    return None


def running(proc: Path = Path("/proc"), root: Path = SESSIONS_ROOT) -> list[OutsideSession]:
    """Every omp session in a terminal: an omp process whose parent is not omp (that would be one of its
    helpers), that has a controlling terminal (a background run has none), and that holds a
    conversation open (a session that has not saved anything yet has nothing to show).

    The controlling terminal is read from `stat`, not from fd/0: omp points its standard input at
    /dev/null while it runs a command, so fd/0 would hide a busy session."""
    root = root.resolve()  # /proc names open files by their real path, symlinks resolved
    stats, found = {}, []
    for folder in proc.iterdir():
        if folder.name.isdigit():
            try:
                stats[int(folder.name)] = _stat_fields((folder / "stat").read_text())
            except (OSError, ValueError, IndexError):
                continue  # the process ended while being read
    ticks, boot = os.sysconf("SC_CLK_TCK"), _boot_time(proc)
    for pid, (parent, name, terminal) in sorted(stats.items()):
        if name != "omp" or not terminal or stats.get(parent, (0, "", 0))[1] == "omp":
            continue
        try:
            path = _open_conversation(proc / str(pid) / "fd", root)
            if path is None:
                continue
            cwd, conversation_id, title = header(path)
            started = boot + int(process_start(pid, proc)) / ticks
            updated = path.stat().st_mtime
        except (OSError, ValueError, TypeError):
            continue  # ended, or not ours to read
        if not cwd or not conversation_id:
            continue
        found.append(OutsideSession(pid=pid, session_id=conversation_id, name=title or f"omp {conversation_id[:8]}",
                                    cwd=cwd, status="unknown", started=started, updated=updated,
                                    program="omp", transcript=str(path)))
    return found


def tool_summary(block: dict) -> str:
    """"bash: Finding the timeout": omp's tools carry a short intent (`i`), else the main argument."""
    args = block.get("arguments") if isinstance(block.get("arguments"), dict) else {}
    detail = args.get("i") or args.get("command") or args.get("path") or args.get("pattern") or ""
    first_line = str(detail).splitlines()[0][:160] if detail else ""
    name = str(block.get("name", "tool"))
    return f"{name}: {first_line}" if first_line else name


def parse_conversation(lines: list[str], limit: int = 40) -> tuple[str | None, list[Item]]:
    """The conversation's latest title and its last `limit` readable items, in the roles the page draws
    (outside.Item): what was typed, the agent's replies, and one line per tool call. Thinking, tool
    output and the messages omp adds by itself (role "developer") are left out."""
    title, items = None, []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") in ("title", "title_change") and isinstance(entry.get("title"), str):
            title = entry["title"]
        if entry.get("type") != "message":
            continue
        message = entry.get("message") or {}
        role, content = message.get("role"), message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            text = str(block.get("text", "")).strip()
            if role == "user" and block.get("type") == "text" and text:
                items.append(Item("you", text))
            elif role == "assistant" and block.get("type") == "text" and text:
                items.append(Item("claude", text))  # the role the page draws an agent's reply with
            elif role == "assistant" and block.get("type") == "toolCall":
                items.append(Item("tool", tool_summary(block)))
    return title, items[-limit:]
