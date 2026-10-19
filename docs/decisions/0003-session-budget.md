# 0003: How many sessions may start (the budget rule)

Date: 2026-10-19

## Context

This laptop: Intel i5-10210U (4 cores, 8 threads), 11.4 GiB RAM, zram plus a swap file.
Running several Claude Code sessions at once, each running builds and tests, has made it freeze and
had desktop apps killed by the kernel's out-of-memory killer.

Measured on 2026-10-19 with `ps -eo rss,args`:

- each `claude` process: 328 MiB and 379 MiB (two sessions open);
- `MemAvailable` while I worked normally (browser, mail, two sessions): about 4.3 to 4.5 GiB.

What a session *starts* (a .NET build, a test suite, a headless browser) uses far more than the
`claude` process itself. I have not measured those peaks yet.

## Decision

The rule lives in `src/ollagi/budget.py`:

| Setting | Value | Where it comes from |
|---------|-------|---------------------|
| `keep_free` | 1.5 GiB | an estimate: room for the desktop and browser to keep working |
| `per_session` | 1.5 GiB | an estimate: about 0.4 GiB measured for `claude` itself, plus about 1 GiB for the builds and tests it runs |
| `max_sessions` | 2 | this hardware; one is the normal case, two is the most it has survived |

A running session's remaining growth (`per_session` minus what it uses now) is set aside before new
sessions are counted. Swap does not count as available memory. A 1-minute load above the number of
CPU threads means no new session at all.

## Why

- `MemAvailable` already includes what running sessions use *now*, but not what they may use in a
  minute when they start a build. Reserving their growth is what stops two "small" sessions from
  later becoming two large ones.
- Swap keeps a machine alive but makes it unusable; planning on it is planning to freeze.

## Open

The two estimates should be replaced by measurement. Step 3 runs each session inside its own
systemd scope, and systemd records the scope's peak memory (`memory.peak`). Once a few real peaks
are recorded, `per_session` becomes a measured number and this record gets a successor.
