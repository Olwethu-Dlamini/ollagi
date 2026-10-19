"""`ollagi doctor`: show the machine's state and whether another session fits.

The report is built by `report()` from values passed in, so tests can check it without touching
the real machine. `run()` is the thin part that reads the real values and prints.

Exit status: 0 when at least one new session fits, 1 when none does. Scripts (and later the
overnight queue) can use it directly: `ollagi doctor && start-the-next-task`.
"""

from ollagi.budget import GIB, Limits, Verdict, how_many_can_start
from ollagi.processes import Session, find_sessions, read_processes
from ollagi.system import MIB, Load, Memory, read_load, read_memory


def report(memory: Memory, load: Load, sessions: list[Session], limits: Limits) -> tuple[str, Verdict]:
    verdict = how_many_can_start(memory, load, [s.tree_rss for s in sessions], limits)
    swap_used = memory.swap_total - memory.swap_free
    lines = [
        f"memory    {memory.available / GIB:.1f} GiB available of {memory.total / GIB:.1f} GiB",
        f"swap      {swap_used / GIB:.1f} GiB used of {memory.swap_total / GIB:.1f} GiB (not counted as available)",
        f"cpu load  {load.one_minute:.2f} (1 min), {load.five_minutes:.2f} (5 min) on {load.cpus} threads",
        f"sessions  {len(sessions)} running",
    ]
    for s in sessions:
        lines.append(f"          pid {s.pid}: {s.tree_rss / MIB:.0f} MiB across {s.processes} processes")
    answer = "yes" if verdict.can_start else "no"
    lines.append(f"start another? {answer}: {verdict.can_start} more can start")
    lines.append(f"          {verdict.reason}")
    return "\n".join(lines), verdict


def run(args) -> int:
    text, verdict = report(read_memory(), read_load(), find_sessions(read_processes()), Limits())
    print(text)
    return 0 if verdict.can_start else 1


def add_to(subparsers) -> None:
    parser = subparsers.add_parser("doctor", help="show free memory, load and whether another session fits")
    parser.set_defaults(handler=run)
