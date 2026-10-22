"""Start, list, read, type into and stop Claude Code sessions kept alive in tmux.

How one session is laid out (docs/decisions/0009 explains why; it replaces the layout in 0005):

    systemd slice  app-ollagi-<name>.slice      the group we measure, freeze and let oomd kill
      scope        ollagi-<name>.scope          holds the tmux server (socket "ollagi-<name>")
      scope        tmux-spawn-<id>.scope        tmux puts each program it starts in its own scope,
                                                inside the same slice; this one runs `claude`

The slice, not the scope, is the session: tmux moves the program it starts out of the server's
scope (tmux is built with systemd support here), but it stays in the server's slice.

tmux keeps the program running when no terminal is attached, and lets us read the screen
(`capture-pane`) and type into it (`send-keys`) from code, which is what the web page does.

A session can be frozen (the RAM watcher does this). Freezing pauses every process in the scope,
the tmux server included, so a frozen session's tmux would never answer. Code that only needs to
know about a session therefore reads the scope's files and the saved session record, never tmux.

Every outside command goes through `run`, a function passed in. Tests pass a fake that records the
commands instead of running them, so the logic is checked without starting tmux or systemd.
"""

import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

PREFIX = "ollagi-"
WINDOW = "main"
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
# Keys the page may press. Anything else is refused, so a request cannot send arbitrary tmux keys.
ALLOWED_KEYS = {"Enter", "Escape", "C-c", "Up", "Down", "Left", "Right", "Tab", "BTab", "Space", "BSpace", "y", "n",
                *"123456789"}
CGROUP_ROOT = Path("/sys/fs/cgroup")
TMUX_CONF = Path(__file__).parent / "tmux.conf"  # ollagi's own tmux settings (see the file)
STATE_DIR = Path.home() / ".local" / "share" / "ollagi" / "sessions"

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
    frozen: bool = False
    program: str = "claude"  # what runs in the window: "claude", or a shell's name ("bash")


def check_name(name: str) -> str:
    if not NAME_PATTERN.match(name):
        raise ValueError("name: 1 to 32 characters, lowercase letters, digits and dashes, starting with a letter or digit")
    return name


def socket_name(name: str) -> str:
    return PREFIX + check_name(name)


def escaped(name: str) -> str:
    """systemd reads "-" in a slice name as nesting (a-b.slice lives inside a.slice), so a session
    called "sd-6641" would sit inside the slice of a session called "sd". "\\x2d" is systemd's way
    of writing a dash that is just a dash."""
    return check_name(name).replace("-", "\\x2d")


def slice_unit(name: str) -> str:
    return f"app-ollagi-{escaped(name)}.slice"


def scope_unit(name: str) -> str:
    return f"ollagi-{escaped(name)}.scope"


def tmux(name: str, *args: str) -> list[str]:
    return ["tmux", "-L", socket_name(name), *args]


def start_command(name: str, directory: str, command: Sequence[str]) -> list[str]:
    """The full command line that starts a session (built separately so tests can read it)."""
    return [
        "systemd-run", "--user", "--scope", "--quiet",
        f"--unit={scope_unit(name).removesuffix('.scope')}",
        f"--slice={slice_unit(name)}",
        f"--description=ollagi session {name}",
        "tmux", "-f", str(TMUX_CONF), "-L", socket_name(name),
        "new-session", "-d", "-s", WINDOW, "-x", "200", "-y", "50", "-c", directory, "--", *command,
    ]


def attach_command(name: str) -> list[str]:
    """Show a session in the current terminal (leave it running with Ctrl-] then d)."""
    return tmux(name, "attach-session", "-t", WINDOW)


def name_for(directory: str, taken: list[str], suffix: str) -> str:
    """A session name from the folder: "/work/Admin-Frontend" -> "admin-frontend-3f2a"."""
    base = re.sub(r"[^a-z0-9-]+", "-", Path(directory).name.lower()).strip("-")[:24] or "session"
    name = f"{base}-{suffix}"
    return name if name not in taken else f"{base}-{suffix}x"


def start(name: str, directory: str, command: Sequence[str] = ("claude",), run: Run = run_command) -> None:
    if not Path(directory).is_dir():
        raise ValueError(f"not a folder: {directory}")
    if name in names(run=run):
        raise ValueError(f"a session called {name} is already running")
    result = run(start_command(name, directory, command))
    if result.returncode != 0:
        raise RuntimeError(f"could not start {name}: {result.stderr.strip()}")
    # If systemd-oomd must kill something under memory pressure, let it pick inside this session.
    run(["systemctl", "--user", "set-property", "--runtime", slice_unit(name), "ManagedOOMMemoryPressure=kill"])
    save_record(name, {"directory": directory, "command": list(command), "created": int(time.time()),
                       "program": program_of(command)})


def login_shell() -> str:
    """My login shell from the password database (the service has no SHELL in its environment)."""
    import pwd

    return pwd.getpwuid(os.getuid()).pw_shell or "bash"


def program_of(command: Sequence[str]) -> str:
    """The name of what a session runs: "claude" for `claude --resume ...`, "bash" for a shell."""
    return Path(command[0]).name if command else "claude"


def save_record(name: str, record: dict, state_dir: Path | None = None) -> None:
    """Remember a session's folder and start time in a small JSON file, readable even when frozen."""
    folder = state_dir or STATE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{check_name(name)}.json").write_text(json.dumps(record))


def load_record(name: str, state_dir: Path | None = None) -> dict:
    try:
        return json.loads(((state_dir or STATE_DIR) / f"{check_name(name)}.json").read_text())
    except (FileNotFoundError, ValueError):
        return {}


def names(socket_dir: Path | None = None, run: Run = run_command) -> list[str]:
    """Names of running ollagi sessions: tmux servers whose socket starts with the prefix."""
    folder = socket_dir or Path(f"/tmp/tmux-{os.getuid()}")
    if not folder.is_dir():
        return []
    found = []
    for sock in sorted(folder.glob(PREFIX + "*")):
        name = sock.name.removeprefix(PREFIX)
        if not NAME_PATTERN.match(name):
            continue
        # A frozen server cannot answer, so check the scope first. Otherwise a socket file can
        # outlive its server; has-session asks the server itself.
        if scope_state(name, run=run)[0] or run(tmux(name, "has-session", "-t", WINDOW)).returncode == 0:
            found.append(name)
    return found


def parse_display(name: str, text: str) -> tuple[str, int, int, bool]:
    """Parse `tmux display` output: "<pane_pid>|<created>|<pane_dead>|<path>"."""
    pid, created, dead, directory = text.strip().split("|", 3)
    return directory, int(pid), int(created), dead != "1"


def info(name: str, run: Run = run_command, cgroup_root: Path = CGROUP_ROOT, state_dir: Path | None = None) -> SessionInfo:
    frozen, current, peak = scope_state(name, run=run, cgroup_root=cgroup_root)
    record = load_record(name, state_dir)
    program = record.get("program", "claude")
    if frozen:
        return SessionInfo(name, record.get("directory", "?"), 0, record.get("created", 0), True, current, peak, True, program)
    shown = run(tmux(name, "display-message", "-p", "-t", WINDOW, "#{pane_pid}|#{session_created}|#{pane_dead}|#{pane_current_path}"))
    directory, pid, created, alive = parse_display(name, shown.stdout)
    return SessionInfo(name, directory, pid, created, alive, current, peak, False, program)


def scope_folder(name: str, run: Run = run_command, cgroup_root: Path = CGROUP_ROOT) -> Path | None:
    """The cgroup folder of the session's slice, or None if it has none."""
    group = run(["systemctl", "--user", "show", "-p", "ControlGroup", "--value", slice_unit(name)]).stdout.strip()
    return cgroup_root / group.lstrip("/") if group else None


def parse_events(text: str) -> bool:
    """cgroup.events holds lines like "populated 1" and "frozen 0"."""
    return any(line.split() == ["frozen", "1"] for line in text.splitlines())


def scope_state(name: str, run: Run = run_command, cgroup_root: Path = CGROUP_ROOT) -> tuple[bool, int | None, int | None]:
    """(frozen, memory.current, memory.peak) read from the slice's files; no tmux involved."""
    folder = scope_folder(name, run=run, cgroup_root=cgroup_root)
    if folder is None:
        return False, None, None

    def number(file: str) -> int | None:
        try:
            return int((folder / file).read_text())
        except (FileNotFoundError, ValueError):
            return None

    try:
        frozen = parse_events((folder / "cgroup.events").read_text())
    except FileNotFoundError:
        frozen = False
    return frozen, number("memory.current"), number("memory.peak")


def freeze(name: str, run: Run = run_command) -> None:
    """Pause every process of the session. Nothing is lost; thaw() continues where it stopped."""
    run(["systemctl", "--user", "freeze", slice_unit(name)])


def thaw(name: str, run: Run = run_command) -> None:
    run(["systemctl", "--user", "thaw", slice_unit(name)])


def screen(name: str, lines: int = 200, colours: bool = False, run: Run = run_command) -> str:
    """The last `lines` lines of the session's window. With colours=True the text keeps the
    terminal's colour codes (`capture-pane -e`), which the page turns into coloured text."""
    flags = ["-p", "-J", *(["-e"] if colours else []), "-t", WINDOW, "-S", f"-{lines}"]
    result = run(tmux(name, "capture-pane", *flags))
    return result.stdout.rstrip("\n")


def leave_scrollback(name: str, run: Run = run_command) -> None:
    """Back to the live screen if the session is scrolled back (tmux's copy mode, entered by a mouse
    wheel or a swipe on the page). There, keys are scroll commands and typed text would be lost."""
    run(tmux(name, "if-shell", "-F", "-t", WINDOW, "#{pane_in_mode}", f"send-keys -t {WINDOW} -X cancel"))


def send_text(name: str, text: str, press_enter: bool = True, run: Run = run_command) -> None:
    leave_scrollback(name, run=run)
    # -l sends the text literally: "Enter" typed as a word stays the word, it is not a key press.
    run(tmux(name, "send-keys", "-t", WINDOW, "-l", text))
    if press_enter:
        run(tmux(name, "send-keys", "-t", WINDOW, "Enter"))


def send_key(name: str, key: str, run: Run = run_command) -> None:
    if key not in ALLOWED_KEYS:
        raise ValueError(f"key not allowed: {key}")
    leave_scrollback(name, run=run)
    run(tmux(name, "send-keys", "-t", WINDOW, key))


def stop(name: str, run: Run = run_command, socket_dir: Path | None = None) -> None:
    """End the session: stopping its tmux server ends the program in it, and the scope with it."""
    if scope_state(name, run=run)[0]:
        thaw(name, run=run)  # a frozen tmux server cannot receive kill-server
    run(tmux(name, "kill-server"))
    # Stopping the slice ends anything still inside it and removes the slice itself.
    run(["systemctl", "--user", "stop", slice_unit(name)])
    # tmux can leave its socket file behind; remove it so the folder only lists live sessions.
    folder = socket_dir or Path(f"/tmp/tmux-{os.getuid()}")
    (folder / socket_name(name)).unlink(missing_ok=True)
