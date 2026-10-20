"""Show a session in a terminal window on this laptop's desktop (docs/decisions/0017).

A session is a tmux server; a window is just one more viewer of it, like the web page. So opening a
window means starting the terminal (foot by default) with `tmux attach` for that session inside.
Closing the window detaches: the session keeps running.

The window is started through `uwsm app --` when uwsm is installed (it is on omarchy). That makes
the window its own systemd unit, so restarting ollagi's service does not close it. Without uwsm the
terminal is started directly, in its own process session.
"""

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ollagi import sessions

DEFAULT_TERMINAL = ("foot", "-T", "ollagi: {name}")


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


def count_windows(name: str, run: sessions.Run = sessions.run_command) -> int:
    """How many terminals show the session now. The web page reads the screen without attaching,
    so only windows (and terminals attached by hand) count."""
    result = run(sessions.tmux(sessions.check_name(name), "list-clients", "-F", "#{client_tty}"))
    if result.returncode != 0:
        return 0
    return len([line for line in result.stdout.splitlines() if line.strip()])


def close_windows(name: str, run: sessions.Run = sessions.run_command) -> int:
    """Close the session's windows by detaching their tmux clients: each window's program ends, so
    the window closes, while the session itself keeps running. Returns how many were closed."""
    open_now = count_windows(name, run=run)
    if open_now:
        run(sessions.tmux(name, "detach-client", "-s", sessions.WINDOW))
    return open_now


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
