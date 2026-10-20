# 0017: A session can also be a terminal window on the laptop

Date: 2026-10-20

## Context

The laptop is the server: every session is a tmux server on it, and the page (or the phone) only
reads and types into it. A session started from the page had no window on the laptop, so to work
on it at the desk I had to attach by hand (`tmux -L ollagi-NAME attach`). I want the session on my
desktop as well, to work on several at once, and to put a window away without ending the session.

## Decision

- A window is one more viewer of the session: the terminal (foot by default) running
  `tmux -L ollagi-NAME attach-session -t main`, titled `ollagi: NAME`. Closing it only detaches.
- It is started through `uwsm app --` (omarchy's way to start a program), which makes the window
  its own systemd unit: restarting ollagi's service does not close it. Without uwsm the terminal
  is started directly in its own process session.
- A session started from the page or with `ollagi start` opens a window. Overnight queue tasks do
  not: I would wake up to a pile of windows. `ollagi start --no-window` skips it once.
- The page's session view has one button, "Open on laptop" or "Close on laptop", decided by how
  many terminals are attached (`tmux list-clients`). The page itself reads the screen without
  attaching, so it never counts as a window. In the terminal: `ollagi open NAME`, `ollagi close NAME`.
- Closing detaches every client of the session (`tmux detach-client -s main`). That also closes a
  terminal I attached by hand, including one from `ollagi here`, because it is the same thing: a
  view of the session on the laptop. The session itself always keeps running.
- Nothing opens when no desktop is running (no `WAYLAND_DISPLAY` or `DISPLAY`); the page then
  says so instead of pretending.
- A frozen session reports no window count: its tmux is paused and would not answer (the command
  would wait 15 s for its timeout).
- Settings, all optional: `[desktop] open_on_start = true`, `terminal = ["foot", "-T", "ollagi: {name}"]`.

## Consequences

- One window costs about 31 MiB (measured: foot 25.5 MiB plus its tmux client 5.2 MiB), against
  330 to 380 MiB for the Claude session itself. Claude runs once however many windows show it.
- The service needs the desktop's environment. The user service gets it from the systemd user
  manager, which omarchy's uwsm fills in at login (checked: `WAYLAND_DISPLAY` is set for ollagi).

## Checked

On the laptop (Hyprland): the page's open, close and open again for a running session showed the
window appear (`hyprctl clients`), the count go 1, 0, 1, and the session stay listed throughout.
`ollagi start wintest /tmp --force -- bash` opened `ollagi: wintest`; `ollagi close wintest`
closed it with the session still running; `ollagi stop wintest` ended it.
