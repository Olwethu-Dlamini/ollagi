# 0005: Each session is its own tmux server inside its own systemd scope

> Superseded in part by 0009: the scope turned out to hold only the tmux server, so sessions are now slices.

Date: 2026-10-19

## Context

A session must keep running when no terminal or phone is looking at it, its screen must be readable
and typable from code, and its memory must be measurable (and later freezable) as one unit,
including every build or test it starts.

## Decision

- tmux keeps the program alive and gives `capture-pane` (read the screen) and `send-keys` (type).
- Each session gets its **own tmux server** (`tmux -L ollagi-<name>`), not a window in a shared
  server. Processes started in tmux are children of the tmux *server*; with one server per session,
  everything a session starts stays together.
- That server is started through `systemd-run --user --scope --unit=ollagi-<name>`. A scope is a
  systemd unit that wraps already-started processes in their own cgroup. The kernel then reports
  the group's memory (`memory.current`, `memory.peak`) and can freeze it (`cgroup.freeze`).
- `ManagedOOMMemoryPressure=kill` on the scope: if systemd-oomd (already running here) must kill
  something under memory pressure, it picks this session instead of the browser.
- Names are restricted to lowercase letters, digits and dashes, because they become socket and unit
  names. Text from the page goes to tmux with `send-keys -l` (literal), and named keys must be in an
  allow-list, so a request cannot press tmux's own control keys.

Checked on this laptop (systemd 261, tmux 3.7c): the scope appears as
`app.slice/ollagi-<name>.scope`, exposes `memory.current`, `memory.peak` and `cgroup.freeze`, and
disappears when the tmux server stops.

## Considered

- One shared tmux server with a window per session: simpler to list, but every session's processes
  would share one cgroup, so per-session memory and freezing would be impossible.
- Running `claude -p` (headless) instead of interactive `claude`: no screen to watch or answer, and
  it encourages fire-and-forget runs that use up subscription limits.
