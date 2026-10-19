# 0016: See sessions started in a terminal, and take an idle one over

Date: 2026-10-19

## Context

Sessions started with plain `claude` in a foot window cannot be read or typed into from outside
(0015). I still want to see them, and to move one into ollagi when I need it on the phone.

## Decision

- Claude Code keeps, per running session, `~/.claude/sessions/<pid>.json` (conversation id,
  folder, name, and its own status: busy, waiting, idle), and the conversation so far in
  `~/.claude/projects/<folder>/<id>.jsonl`. ollagi reads both (`src/ollagi/outside.py`):
  sessions appear on the home screen with a "terminal" tag (busy = working, waiting = needs you,
  idle = done), and tapping one shows its recent conversation, read only.
- A session file is trusted only if the process with that pid has the start time the file
  recorded: pid numbers are reused, so a leftover file must not name some other process.
- **Take over** (idle sessions only, the session's name typed to confirm): ollagi sends SIGTERM to
  that Claude, which lets it save and exit, waits up to 10 s, then starts
  `claude --resume <id>` as an ollagi session in the same folder. The terminal window gets its
  prompt back; `tmux -L ollagi-<name> attach` shows the session there again.

## Limits

- These are Claude Code's internal files (seen in 2.1.280), not a published format. Fields are
  read defensively, and a file that does not parse is skipped; a new Claude version may need
  `outside.py` adjusted.
- Take over was tested with fakes, not yet on a real session: it ends a real window's Claude, so
  the first real use should be a throwaway session.
- Each session also has a messaging socket (`/run/user/<uid>/cc-socks/<pid>.sock`) that Claude
  Code uses between its own sessions; using it would mean depending on an undocumented protocol,
  so ollagi does not.

## Checked

Tests with invented files: stale session files are skipped, subagent entries and thinking are
left out, the tail of a large file drops its cut first line, take over refuses a busy session and
a wrong name and reopens with `--resume` and the same id. On the real page: the 4 terminal
sessions appeared with their states, and an idle one's conversation opened with Take over offered
(not pressed).
