# 0033: Resume an earlier conversation from the phone

Date: 2026-10-22

Follows 0016 (sessions started in a terminal, read from Claude's own files).

## Context

A conversation ends with its session (a reboot, a stop, the RAM watcher). From the laptop,
`claude --resume` brings it back; from the phone there was only take-over of a running one.

## Decision

- `outside.recent_conversations(folder)` lists the newest files in the folder's project directory
  under `~/.claude/projects` (the path with every character that is not a letter or digit turned
  into a dash: `/work/DATA!` → `-work-DATA-`, seen in Claude Code 2.1.280), each with the name
  Claude gave it (the last `ai-title` entry) or else its first typed line, and the file's last
  change. Empty files are skipped.
- `GET /api/conversations?directory=` offers them, newest first, leaving out any conversation
  running right now: Claude Code's own session files (0016) list every running Claude, in a
  window or in an ollagi session, so neither is offered twice.
- The New sheet shows them once a folder is chosen: "start a new conversation" first, then
  "resume: title (age ago)". Picking one starts `claude --resume ID`.
- The server accepts only an id from that same list, never an arbitrary word on claude's command
  line, and only for a Claude session. The check runs before the budget, so a bad request is 400
  even when memory is short.

## Consequences

- The project folder encoding is Claude Code's internal choice; if it changes, the list is empty
  and nothing else breaks.
- The folder of this very session, with one conversation file, offers nothing while it runs.
- Undo: remove the picker, the route and `resume` from `StartRequest`.

## Checked

2026-10-22: 260 unit tests (title from ai-title, else first typed line; newest first; empty files
skipped; a running conversation left out; a bad id, a shell with an id, and an id with memory short
all 400). Headless Chromium with two invented conversations for /tmp: the picker appeared with three
choices after choosing the folder; the API refused `--version` as an id.

Not yet checked: a real resume from the phone.
