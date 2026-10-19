"""Find the Claude Code sessions running on this machine and the memory each one uses.

A session is more than the `claude` process: the builds, tests and browsers it starts are its
children, and they are usually the heavy part. So a session's memory is the sum over its whole
process tree (the `claude` process and every descendant).

Every process has a folder /proc/<pid>/ with:
- `stat`: one line; the name is in brackets and the parent's pid (ppid) follows it;
- `status`: lines like "VmRSS:   388096 kB", the RAM the process holds right now.

Summing RSS over a tree counts memory shared between processes (libraries, for example) more than
once, so the total is a slight overestimate. For deciding "is there room?", erring high is safe.
"""

from dataclasses import dataclass
from pathlib import Path

from ollagi.system import KIB

SESSION_NAME = "claude"


@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    name: str
    rss: int  # bytes


@dataclass(frozen=True)
class Session:
    pid: int
    tree_rss: int  # bytes, the claude process plus all its descendants
    processes: int  # how many processes are in the tree


def parse_stat(text: str) -> tuple[str, int]:
    """Return (name, ppid) from the text of /proc/<pid>/stat.

    The name sits between the first "(" and the LAST ")", because a name may itself contain
    brackets or spaces. The fields after it start with the state, then the ppid.
    """
    name = text[text.index("(") + 1 : text.rindex(")")]
    after = text[text.rindex(")") + 2 :].split()
    return name, int(after[1])


def parse_rss(status_text: str) -> int:
    for line in status_text.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) * KIB
    return 0  # kernel threads have no VmRSS line


def find_sessions(procs: list[Proc]) -> list[Session]:
    """Group processes into Claude sessions.

    A session is a `claude` process whose parent is not itself a `claude` process (a claude
    started by another claude belongs to the outer session).
    """
    by_pid = {p.pid: p for p in procs}
    children: dict[int, list[Proc]] = {}
    for p in procs:
        children.setdefault(p.ppid, []).append(p)

    def is_session_root(p: Proc) -> bool:
        parent = by_pid.get(p.ppid)
        return p.name == SESSION_NAME and not (parent and parent.name == SESSION_NAME)

    sessions = []
    for root in (p for p in procs if is_session_root(p)):
        total, count, stack = 0, 0, [root]
        while stack:  # walk the tree without recursion, so deep trees cannot overflow the stack
            p = stack.pop()
            total += p.rss
            count += 1
            stack.extend(children.get(p.pid, []))
        sessions.append(Session(pid=root.pid, tree_rss=total, processes=count))
    return sorted(sessions, key=lambda s: s.pid)


def read_processes(proc: Path = Path("/proc")) -> list[Proc]:
    procs = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:  # a process can exit between listing the folder and reading its files
            name, ppid = parse_stat((entry / "stat").read_text())
            rss = parse_rss((entry / "status").read_text())
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
        procs.append(Proc(pid=int(entry.name), ppid=ppid, name=name, rss=rss))
    return procs
