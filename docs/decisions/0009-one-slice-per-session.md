# 0009: Each session is a systemd slice, not a scope (replaces the layout in 0005)

Date: 2026-10-19

## What went wrong with 0005

0005 put each session's tmux server in its own scope and measured and froze that scope. Testing the
RAM watcher showed the scope held **only the tmux server**: a session holding 60 MiB reported 1 MiB.
tmux on this machine is built with systemd support, and it moves every program it starts into a new
scope of its own (`tmux-spawn-<id>.scope`). So the earlier numbers measured tmux, not Claude, and
freezing the scope froze tmux while the program underneath kept running and kept growing. The first
real-session test passed anyway, because it only checked that memory was above zero.

## Decision

- Start the tmux server with `systemd-run --user --scope --slice=app-ollagi-<name>.slice`.
  tmux places the programs it starts in scopes inside the **same slice**, so the slice holds the
  whole session. Measuring (`memory.current`, `memory.peak`) and freezing are done on the slice.
- Slices live under `app.slice/app-ollagi.slice/`, inside the group systemd-oomd already watches,
  and each session slice gets `ManagedOOMMemoryPressure=kill`. (The property is set and reported
  back by systemd; whether oomd lists the slice as monitored was not confirmed.)
- Dashes in names are escaped as `\x2d`. systemd reads `a-b.slice` as a child of `a.slice`, so
  unescaped, `sd-6641` would live inside the slice of a session called `sd`, and freezing `sd`
  would freeze both.
- Stopping a session also stops its slice, which ends anything left inside.

## Evidence (this laptop, 2026-10-19)

- A program holding 60 MiB: scope 1 MiB (wrong), slice 64 MiB.
- The real-session test now requires at least 30 MiB from a program holding 30 MiB; pointing the
  code back at the scope makes it fail.
- With an always-red test config, the watcher froze the 65 MiB session after 3 s and the 2 MiB one
  3 s later; after thawing, a counter in the frozen session continued from 13 to 14, nothing lost.
