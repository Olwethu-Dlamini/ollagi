"""Show a session in a terminal window on this laptop's desktop (docs/decisions/0017).

A session is a tmux server; a window is just one more viewer of it, like the web page. So opening a
window means starting the terminal (foot by default) with `tmux attach` for that session inside.
Closing the window detaches: the session keeps running.

The window is started through `uwsm app --` when uwsm is installed (it is on omarchy). That makes
the window its own systemd unit, so restarting ollagi's service does not close it. Without uwsm the
terminal is started directly, in its own process session.

The page can also show a session as a live terminal in the browser (docs/decisions/0018). That is a
tmux client too, but it is not a window on the laptop, so it must not be counted or closed here.
Its process carries OLLAGI_VIEWER=browser in its environment, which is how it is told apart.
"""

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ollagi import sessions

DEFAULT_TERMINAL = ("foot", "-T", "ollagi: {name}")
BROWSER_MARK = b"OLLAGI_VIEWER=browser"  # in the environment of a browser terminal's tmux client


@dataclass(frozen=True)
class Settings:
    open_on_start: bool = True          # a session started from the page or `ollagi start` opens a window
    terminal: tuple[str, ...] = DEFAULT_TERMINAL   # "{name}" is replaced by the session name


def has_desktop(environ: Mapping[str, str]) -> bool:
    """A window can only appear when a graphical session is running (Wayland, or X as a fallback)."""
    return bool(environ.get("WAYLAND_DISPLAY") or environ.get("DISPLAY"))


def default_launcher() -> list[str]:
    return ["uwsm", "app", "--"] if shutil.which("uwsm") else []


def window_command(name: str, settings: Settings, environ: Mapping[str, str],
                   launcher: Sequence[str] | None = None) -> list[str] | None:
    """The command that opens a window showing the session, or None when there is no desktop."""
    if not has_desktop(environ):
        return None
    sessions.check_name(name)
    prefix = default_launcher() if launcher is None else list(launcher)
    terminal = [part.replace("{name}", name) for part in settings.terminal]
    return [*prefix, *terminal, *sessions.attach_command(name)]


def open_window(name: str, settings: Settings, environ: Mapping[str, str] | None = None,
                popen: Callable = subprocess.Popen, launcher: Sequence[str] | None = None) -> bool:
    """Open the window without waiting for it. Returns False when there is no desktop to show it on."""
    command = window_command(name, settings, os.environ if environ is None else environ, launcher)
    if command is None:
        return False
    # Its own process session and no shared input or output, so the window does not belong to us.
    popen(command, start_new_session=True,
          stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def read_environ(pid: int) -> bytes:
    """A process's environment as the kernel keeps it: NAME=value entries separated by NUL bytes."""
    return Path(f"/proc/{pid}/environ").read_bytes()


def in_browser(pid: int, read: Callable[[int], bytes] = read_environ) -> bool:
    try:
        return BROWSER_MARK in read(pid).split(b"\0")
    except OSError:
        return False  # gone or unreadable: treat it as a window, the old behaviour


def laptop_windows(name: str, run: sessions.Run = sessions.run_command,
                   read_environ: Callable[[int], bytes] = read_environ) -> list[str]:
    """The terminals (ttys) showing the session on the laptop. The page's plain screen view reads
    the screen without attaching, and a live terminal in the browser is left out, so only windows
    (and terminals attached by hand) are listed."""
    result = run(sessions.tmux(sessions.check_name(name), "list-clients", "-F", "#{client_tty} #{client_pid}"))
    if result.returncode != 0:
        return []
    windows = []
    for line in result.stdout.splitlines():
        tty, _, pid = line.strip().rpartition(" ")
        if tty and pid.isdigit() and not in_browser(int(pid), read_environ):
            windows.append(tty)
    return windows


def count_windows(name: str, run: sessions.Run = sessions.run_command,
                  read_environ: Callable[[int], bytes] = read_environ) -> int:
    """How many windows show the session on the laptop now."""
    return len(laptop_windows(name, run=run, read_environ=read_environ))


def close_windows(name: str, run: sessions.Run = sessions.run_command,
                  read_environ: Callable[[int], bytes] = read_environ) -> int:
    """Close the session's windows by detaching their tmux clients one by one: each window's
    program ends, so the window closes, while the session itself keeps running. A live terminal in
    the browser stays open. Returns how many were closed."""
    windows = laptop_windows(name, run=run, read_environ=read_environ)
    for tty in windows:
        run(sessions.tmux(name, "detach-client", "-t", tty))
    return len(windows)


class Laptop:
    """The three things the web page can do with windows, bound to the configured settings."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def open(self, name: str) -> bool:
        return open_window(name, self.settings)

    def count(self, name: str) -> int:
        return count_windows(name)

    def close(self, name: str) -> int:
        return close_windows(name)
