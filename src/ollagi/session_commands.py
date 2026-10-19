"""Terminal commands for sessions: start, list, show, send, stop.

These are thin: they read the arguments, call sessions.py, and print. `start` first asks the budget
rule whether another session fits, and refuses unless --force is given.
"""

import time

from ollagi import sessions
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
    print(f"watch it:  tmux -L ollagi-{args.name} attach   (leave with Ctrl-b then d)")
    return 0


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
    p.add_argument("command", nargs="*", help="program to run instead of claude, after --")
    p.set_defaults(handler=cmd_start)

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
