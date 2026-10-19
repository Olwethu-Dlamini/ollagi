"""Decide how many more Claude Code sessions this machine can safely start.

The rule, in words (docs/decisions/0003 explains the numbers):

1. Keep `keep_free` bytes for everything else (desktop, browser, editor). Never plan to use them.
2. Each session may grow to `per_session` bytes. A running session that uses less than that today
   may still grow, so its remaining growth is set aside too.
3. Whatever is left, divided by `per_session`, is how many new sessions fit.
4. Never exceed `max_sessions` running at once, however much RAM is free.
5. If the CPUs are already overloaded (1-minute load above the number of CPU threads), start none.

Swap is ignored on purpose: a session that needs swap to run makes the whole machine crawl.
"""

from dataclasses import dataclass

from ollagi.system import MIB, Load, Memory

GIB = 1024 * MIB


@dataclass(frozen=True)
class Limits:
    keep_free: int = int(1.5 * GIB)
    per_session: int = int(1.5 * GIB)
    max_sessions: int = 2


@dataclass(frozen=True)
class Verdict:
    can_start: int
    reason: str


def how_many_can_start(
    memory: Memory, load: Load, running_session_bytes: list[int], limits: Limits = Limits()
) -> Verdict:
    """Return how many new sessions fit, with the reason in plain words."""
    running = len(running_session_bytes)

    if load.one_minute > load.cpus:
        return Verdict(0, f"CPU overloaded: load {load.one_minute:.1f} on {load.cpus} threads")

    if running >= limits.max_sessions:
        return Verdict(0, f"{running} sessions running, the limit is {limits.max_sessions}")

    growth_reserved = sum(max(0, limits.per_session - used) for used in running_session_bytes)
    room = memory.available - limits.keep_free - growth_reserved
    fit_by_memory = max(0, room // limits.per_session)
    can_start = min(fit_by_memory, limits.max_sessions - running)

    reason = (
        f"{_gib(memory.available)} available, minus {_gib(limits.keep_free)} kept free, "
        f"minus {_gib(growth_reserved)} growth room for {running} running session(s), "
        f"leaves {_gib(max(0, room))}; each new session needs {_gib(limits.per_session)}"
    )
    return Verdict(int(can_start), reason)


def _gib(n: int) -> str:
    return f"{n / GIB:.1f} GiB"
