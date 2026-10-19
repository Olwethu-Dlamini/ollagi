# 0004: No fixed session cap; memory and load decide (replaces the cap in 0003)

Date: 2026-10-19

## Context

0003 set `max_sessions = 2` and called two "the most it has survived". That wording was wrong:
there is no record of what this machine survives. The 2 came from one incident (3 October 2026:
two sessions ran several .NET test suites while a stray `find /` crawled the disk; load reached
25 to 30 and the desktop's Brave and Telegram were killed) and from two sessions running fine today
because they were not building anything.

So a session count is the wrong thing to limit. Two idle sessions are harmless; two sessions each
running a test suite are not. What hurts is memory and CPU, and those can be measured.

## Decision

- Remove `max_sessions`. A new session may start when the budget rule in `budget.py` says it fits:
  memory after the reserve and the running sessions' growth room, and CPU load under the number of
  threads.
- Protection while sessions run comes from a RAM watcher (a later step) that reads memory pressure
  (`/proc/pressure/memory`) and acts before the machine stalls, and from systemd-oomd, which is
  already running here.

## Consequences

- With plenty of free memory, several sessions may start. Each still costs subscription usage.
- Until the watcher exists, a session that grows quickly is only caught by systemd-oomd. Step 3
  runs each session in its own systemd scope marked so that oomd kills that session, not the browser.
