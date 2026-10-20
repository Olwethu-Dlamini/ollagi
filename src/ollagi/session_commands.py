"""Terminal commands for sessions: start, here, open, close, list, show, send, stop.

These are thin: they read the arguments, call sessions.py, and print. `start` first asks the budget
rule whether another session fits, and refuses unless --force is given. `here` starts Claude in the
current folder and shows it in this terminal, like typing `claude`. `start` also opens a window on the
laptop's desktop (docs/decisions/0017), `open` does that for a session already running and `close` closes
its windows without stopping it.

The program `here` runs is `claude`, or whatever OLLAGI_CLAUDE names (tests use a harmless shell;
it could also be another command-line agent).
"""

import os
import secrets
import sys
import time

from ollagi import config, desktop, sessions
from ollagi.budget import Limits, how_many_can_start
from ollagi.processes import find_sessions, read_processes
from ollagi.system import MIB, read_load, read_memory


def cmd_start(args) -> int:
    if not args.force:
        running = [s.tree_rss for s in find_sessions(read_processes())]
        verdict = how_many_can_start(read_memory(), read_load(), running, Limits())
        if not verdict.can_start:
            print(f"not starting: {verdict.reason}\n(use --force to start anyway)")
            return 1
    command = args.command or ["claude"]
    sessions.start(args.name, args.directory, command)
    print(f"started {args.name} in {args.directory}: {' '.join(command)}")
    settings = config.load().desktop
    if not args.no_window and settings.open_on_start and desktop.open_window(args.name, settings):
        print("opened in a window on the desktop (closing it leaves the session running)")
    else:
        print(f"watch it:  tmux -L ollagi-{args.name} attach   (leave with Ctrl-] then d)")
    return 0


def cmd_open(args) -> int:
    """Show a running session in a new terminal window on this laptop."""
    if args.name not in sessions.names():
        print(f"no ollagi session called {args.name} (see `ollagi list`)")
        return 1
    if not desktop.open_window(args.name, config.load().desktop):
        print("no desktop is running to show it on; use `tmux -L ollagi-NAME attach` in a terminal".replace("NAME", args.name))
        return 1
    print(f"opened {args.name} in a window (closing it leaves the session running)")
    return 0


def cmd_close(args) -> int:
    """Close the session's windows on this laptop; the session keeps running."""
    if args.name not in sessions.names():
        print(f"no ollagi session called {args.name} (see `ollagi list`)")
        return 1
    closed = desktop.close_windows(args.name)
    print(f"closed {closed} window(s) of {args.name}; it keeps running" if closed else f"{args.name} has no window open")
    return 0


def cmd_here(args) -> int:
    """Start Claude here through ollagi, then show it in this terminal, like running `claude`."""
    program = os.environ.get("OLLAGI_CLAUDE", "claude")
    if os.environ.get("TMUX"):
        # Already inside tmux (maybe an ollagi session itself): just run the program normally.
        os.execvp(program, [program, *args.claude_args])
    directory = os.getcwd()
    name = args.name or sessions.name_for(directory, sessions.names(), secrets.token_hex(2))
    running = [s.tree_rss for s in find_sessions(read_processes())]
    verdict = how_many_can_start(read_memory(), read_load(), running, Limits())
    if not verdict.can_start:
        # Starting is my explicit choice here, so warn instead of refusing.
        print(f"ollagi: memory is short ({verdict.reason}); starting anyway", file=sys.stderr)
    sessions.start(name, directory, [program, *args.claude_args])
    print(f"ollagi session {name} (on the phone page too). Leave it running with Ctrl-] then d.")
    time.sleep(0.2)
    # exec replaces this program with tmux, so the terminal shows the session directly.
    os.execvp("tmux", sessions.attach_command(name))


def cmd_list(args) -> int:
    found = sessions.names()
    if not found:
        print("no ollagi sessions running")
    for name in found:
        s = sessions.info(name)
        memory = f"{s.memory_current / MIB:.0f} MiB (peak {s.memory_peak / MIB:.0f})" if s.memory_current else "memory unknown"
        state = "running" if s.alive else "program exited"
        age = int((time.time() - s.created) / 60)
        print(f"{name:<20} {state:<15} {memory:<26} {age} min  {s.directory}")
    return 0


def cmd_show(args) -> int:
    print(sessions.screen(args.name, lines=args.lines))
    return 0


def cmd_send(args) -> int:
    if args.key:
        sessions.send_key(args.name, args.key)
    else:
        sessions.send_text(args.name, " ".join(args.text))
    return 0


def cmd_stop(args) -> int:
    sessions.stop(args.name)
    print(f"stopped {args.name}")
    return 0


def add_to(subparsers) -> None:
    p = subparsers.add_parser("start", help="start a Claude Code session in tmux")
    p.add_argument("name", help="short name, e.g. sd-6641")
    p.add_argument("directory", help="the project folder to start in")
    p.add_argument("--force", action="store_true", help="start even if the budget says there is no room")
    p.add_argument("--no-window", action="store_true", help="do not open a terminal window on the desktop")
    p.add_argument("command", nargs="*", help="program to run instead of claude, after --")
    p.set_defaults(handler=cmd_start)

    p = subparsers.add_parser("here", help="start Claude in this folder through ollagi and show it here")
    p.add_argument("--name", help="session name (default: the folder's name plus 4 random characters)")
    p.add_argument("claude_args", nargs="*", help="passed on to claude, after --, e.g. -- --continue")
    p.set_defaults(handler=cmd_here)

    p = subparsers.add_parser("open", help="show a running session in a terminal window on the desktop")
    p.add_argument("name")
    p.set_defaults(handler=cmd_open)

    p = subparsers.add_parser("close", help="close a session's terminal windows; the session keeps running")
    p.add_argument("name")
    p.set_defaults(handler=cmd_close)

    p = subparsers.add_parser("list", help="list running sessions")
    p.set_defaults(handler=cmd_list)

    p = subparsers.add_parser("show", help="print the end of a session's screen")
    p.add_argument("name")
    p.add_argument("--lines", type=int, default=40)
    p.set_defaults(handler=cmd_show)

    p = subparsers.add_parser("send", help="type text (and Enter) into a session, or press one key")
    p.add_argument("name")
    p.add_argument("text", nargs="*")
    p.add_argument("--key", choices=sorted(sessions.ALLOWED_KEYS))
    p.set_defaults(handler=cmd_send)

    p = subparsers.add_parser("stop", help="stop a session")
    p.add_argument("name")
    p.set_defaults(handler=cmd_stop)
