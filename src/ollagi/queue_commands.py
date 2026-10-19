"""Terminal commands for the overnight queue: ollagi queue add | list | cancel | pause | resume.

They only change the queue's database; the server (`ollagi serve`) is what starts the tasks.
"""

import time
from pathlib import Path

from ollagi.queue import Store


def cmd_add(args) -> int:
    task = Store().add(str(Path(args.directory).resolve()), " ".join(args.prompt))
    print(f"queued task {task.id} in {task.directory}")
    return 0


def cmd_list(args) -> int:
    store = Store()
    print("queue is PAUSED: " + store.pause_reason() if store.paused() else "queue is running")
    for t in store.all():
        when = time.strftime("%H:%M", time.localtime(t.finished or t.started or t.created))
        note = f"  ({t.note})" if t.note else ""
        print(f"#{t.id:<4} {t.status:<10} {when}  {t.prompt[:60]}{note}")
    return 0


def cmd_cancel(args) -> int:
    Store().cancel(args.id)
    print(f"cancelled task {args.id}")
    return 0


def cmd_pause(args) -> int:
    Store().set_paused(True, "paused by hand")
    print("queue paused")
    return 0


def cmd_resume(args) -> int:
    Store().set_paused(False)
    print("queue resumed")
    return 0


def add_to(subparsers) -> None:
    queue = subparsers.add_parser("queue", help="the overnight queue: add, list, cancel, pause, resume")
    actions = queue.add_subparsers(dest="queue_command", metavar="<action>", required=True)

    p = actions.add_parser("add", help="queue a task: a folder and what Claude should do")
    p.add_argument("directory")
    p.add_argument("prompt", nargs="+")
    p.set_defaults(handler=cmd_add)

    actions.add_parser("list", help="list tasks").set_defaults(handler=cmd_list)

    p = actions.add_parser("cancel", help="cancel a queued task")
    p.add_argument("id", type=int)
    p.set_defaults(handler=cmd_cancel)

    actions.add_parser("pause", help="hold the queue").set_defaults(handler=cmd_pause)
    actions.add_parser("resume", help="release the queue").set_defaults(handler=cmd_resume)
