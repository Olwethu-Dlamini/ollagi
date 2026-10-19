# 0015: Typing `claude` in a terminal starts it through ollagi

Date: 2026-10-19

## Context

I start most sessions by typing `claude` in a foot terminal window. Such a session belongs to that
window: foot has no remote control, and the kernel's way of typing into another terminal
(`TIOCSTI`) is disabled here (`dev.tty.legacy_tiocsti = 0`, which is right for security). So
ollagi could count those sessions but never read or answer them.

## Decision

- `ollagi here [-- claude options]` starts Claude in the current folder as an ollagi session, then
  `exec`s `tmux attach`, so the terminal shows it directly. The session is named after the folder
  plus 4 random characters (`data-3f2a`).
- ollagi sessions use their own tmux settings (`src/ollagi/tmux.conf`, passed with `-f`; my
  `~/.tmux.conf` is not touched): no status bar, so it looks like a plain terminal; Esc reacts in
  10 ms instead of tmux's 500; the tmux command key is Ctrl-] instead of Ctrl-b, because Claude
  Code uses Ctrl-b itself. Ctrl-] then d leaves a session running without the window.
- `deploy/claude-wrapper.bash` defines a `claude` shell function, loaded from `~/.bashrc` (one line,
  backup in `~/.bashrc.before-ollagi`). It calls `ollagi here` only for an interactive chat at a
  terminal; print mode, help, version, subcommands (`claude mcp`, `claude doctor`...), non-terminal
  use and anything already inside tmux go straight to the real `claude`.
- `OLLAGI_CLAUDE` names the program to run instead of `claude`: tests use a shell, and it could be
  another command-line agent.

## Consequences

- Closing the terminal window no longer ends the session: it keeps running in ollagi (stop it from
  the page, or `ollagi stop <name>`). That is the point, and also a change of habit.
- `command claude` or `OLLAGI_OFF=1 claude` skips ollagi once.

## Checked

In a real pseudo-terminal: `claude` through the function became ollagi session `tmp-8b15`, visible
in `ollagi list` while attached, with the tmux settings active (prefix C-], escape-time 10, status
off); `claude --version` and `claude doctor --help` went to the real claude and made no session.
