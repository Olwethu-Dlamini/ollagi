# 0008: A RAM watcher that freezes the heaviest session when memory runs out

Date: 2026-10-19

## Context

With no fixed session cap (0004), something must step in while sessions run. Linux already has
systemd-oomd here: when memory pressure in `app.slice` stays above 50% for 20 seconds, it kills
the biggest app in that group, which is how Brave and Telegram died on 3 October. By then the
machine has been crawling for a while, and it kills by size, not by blame.

## Decision

`src/ollagi/watcher.py`, running inside the ollagi server every 2 seconds:

| Level | When (defaults) | Effect |
|-------|-----------------|--------|
| green | at least 1.5 GiB available and pressure at most 10% | normal |
| amber | under 1.5 GiB, or pressure over 10% | the budget rule already refuses new sessions |
| red | under 0.75 GiB, or pressure over 30% | after 10 s of red: act on the heaviest ollagi session |

- Default action **freeze**: `systemctl --user freeze` pauses every process in the session's scope.
  Memory it holds stays held, but it stops *growing*, which is what turns a slow machine into a dead
  one. Nothing is lost; after 60 s of green the watcher thaws it.
- One session per red period, heaviest first, so it never freezes everything at once.
- It only touches sessions it froze itself, and only ollagi sessions. Sessions started outside
  ollagi, and every other program, are left to systemd-oomd.
- `action = "stop"` or `"warn"` in the config file changes the behaviour (decision left open to me).

The thresholds are starting values chosen to act well before oomd's 50%/20 s, not measured limits.
The watcher's event log (shown on the page) is how they get checked against real days.

## Consequences

- Freezing a session also freezes its tmux server, so its screen cannot be read until thawed
  (0005 and `sessions.py` handle this without hanging).
- A frozen session still holds its memory. If the machine stays red with everything frozen, oomd
  remains the last resort, and each scope is marked so oomd picks a session over the browser.
