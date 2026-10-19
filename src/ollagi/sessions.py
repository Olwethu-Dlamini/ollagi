"""Start, list, read, type into and stop Claude Code sessions kept alive in tmux.

How one session is laid out (docs/decisions/0005 explains why):

    systemd scope  ollagi-<name>.scope      a group systemd can measure, freeze or kill as one
      tmux server  socket "ollagi-<name>"   its own server, so the scope holds only this session
        session "main", one window         runs `claude` in the project folder

tmux keeps the program running when no terminal is attached, and lets us read the screen
(`capture-pane`) and type into it (`send-keys`) from code, which is what the web page does.

Every outside command goes through `run`, a function passed in. Tests pass a fake that records the
commands instead of running them, so the logic is checked without starting tmux or systemd.
"""

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

PREFIX = "ollagi-"
WINDOW = "main"
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# Keys the page may press. Anything else is refused, so a request cannot send arbitrary tmux keys.
ALLOWED_KEYS = {"Enter", "Escape", "C-c", "Up", "Down", "Left", "Right", "Tab", "BTab", "y", "n", "1", "2", "3"}
CGROUP_ROOT = Path("/sys/fs/cgroup")

Run = Callable[[Sequence[str]], subprocess.CompletedProcess]


def run_command(argv: Sequence[str]) -> subprocess.CompletedProcess:
    """Run a program and capture its output. Never goes through a shell, so text is never parsed as code."""
    return subprocess.run(list(argv), capture_output=True, text=True, timeout=15)


@dataclass(frozen=True)
class SessionInfo:
    name: str
    directory: str
    pane_pid: int
    created: int  # unix time
    alive: bool  # False once the program in the window has exited
    memory_current: int | None  # bytes, from the scope's cgroup; None if unknown
    memory_peak: int | None


def check_name(name: str) -> str:
    if not NAME_PATTERN.match(name):
        raise ValueError("name: 1 to 32 characters, lowercase letters, digits and dashes, starting with a letter or digit")
    return name


def socket_name(name: str) -> str:
    return PREFIX + check_name(name)


def tmux(name: str, *args: str) -> list[str]:
    return ["tmux", "-L", socket_name(name), *args]


def start_command(name: str, directory: str, command: Sequence[str]) -> list[str]:
    """The full command line that starts a session (built separately so tests can read it)."""
    return [
        "systemd-run", "--user", "--scope", "--quiet",
        f"--unit={socket_name(name)}",
        f"--description=ollagi session {name}",
        # If systemd-oomd must kill something under memory pressure, prefer this session.
        "-p", "ManagedOOMMemoryPressure=kill",
        *tmux(name, "new-session", "-d", "-s", WINDOW, "-x", "200", "-y", "50", "-c", directory, "--", *command),
    ]


def start(name: str, directory: str, command: Sequence[str] = ("claude",), run: Run = run_command) -> None:
    if not Path(directory).is_dir():
        raise ValueError(f"not a folder: {directory}")
    if name in names(run=run):
        raise ValueError(f"a session called {name} is already running")
    result = run(start_command(name, directory, command))
    if result.returncode != 0:
        raise RuntimeError(f"could not start {name}: {result.stderr.strip()}")


def names(socket_dir: Path | None = None, run: Run = run_command) -> list[str]:
    """Names of running ollagi sessions: tmux servers whose socket starts with the prefix."""
    folder = socket_dir or Path(f"/tmp/tmux-{os.getuid()}")
    if not folder.is_dir():
        return []
    found = []
    for sock in sorted(folder.glob(PREFIX + "*")):
        name = sock.name.removeprefix(PREFIX)
        # A socket file can outlive its server; has-session asks the server itself.
        if NAME_PATTERN.match(name) and run(tmux(name, "has-session", "-t", WINDOW)).returncode == 0:
            found.append(name)
    return found


def parse_display(name: str, text: str) -> tuple[str, int, int, bool]:
    """Parse `tmux display` output: "<pane_pid>|<created>|<pane_dead>|<path>"."""
    pid, created, dead, directory = text.strip().split("|", 3)
    return directory, int(pid), int(created), dead != "1"


def info(name: str, run: Run = run_command, cgroup_root: Path = CGROUP_ROOT) -> SessionInfo:
    shown = run(tmux(name, "display-message", "-p", "-t", WINDOW, "#{pane_pid}|#{session_created}|#{pane_dead}|#{pane_current_path}"))
    directory, pid, created, alive = parse_display(name, shown.stdout)
    current, peak = scope_memory(name, run=run, cgroup_root=cgroup_root)
    return SessionInfo(name, directory, pid, created, alive, current, peak)


def scope_memory(name: str, run: Run = run_command, cgroup_root: Path = CGROUP_ROOT) -> tuple[int | None, int | None]:
    """Read memory.current and memory.peak from the session's systemd scope, if it has one."""
    unit = socket_name(name) + ".scope"
    group = run(["systemctl", "--user", "show", "-p", "ControlGroup", "--value", unit]).stdout.strip()
    if not group:
        return None, None
    folder = cgroup_root / group.lstrip("/")
    values = []
    for file in ("memory.current", "memory.peak"):
        try:
            values.append(int((folder / file).read_text()))
        except (FileNotFoundError, ValueError):
            values.append(None)
    return values[0], values[1]


def screen(name: str, lines: int = 200, run: Run = run_command) -> str:
    """The last `lines` lines of the session's window, as plain text."""
    result = run(tmux(name, "capture-pane", "-p", "-J", "-t", WINDOW, "-S", f"-{lines}"))
    return result.stdout.rstrip("\n")


def send_text(name: str, text: str, press_enter: bool = True, run: Run = run_command) -> None:
    # -l sends the text literally: "Enter" typed as a word stays the word, it is not a key press.
    run(tmux(name, "send-keys", "-t", WINDOW, "-l", text))
    if press_enter:
        run(tmux(name, "send-keys", "-t", WINDOW, "Enter"))


def send_key(name: str, key: str, run: Run = run_command) -> None:
    if key not in ALLOWED_KEYS:
        raise ValueError(f"key not allowed: {key}")
    run(tmux(name, "send-keys", "-t", WINDOW, key))


def stop(name: str, run: Run = run_command, socket_dir: Path | None = None) -> None:
    """End the session: stopping its tmux server ends the program in it, and the scope with it."""
    run(tmux(name, "kill-server"))
    # tmux can leave its socket file behind; remove it so the folder only lists live sessions.
    folder = socket_dir or Path(f"/tmp/tmux-{os.getuid()}")
    (folder / socket_name(name)).unlink(missing_ok=True)
