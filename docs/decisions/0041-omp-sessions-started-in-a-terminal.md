# 0041: omp sessions started in a terminal show on the page, read only

Date: 2026-11-09

## Context

The page lists sessions started in a terminal window next to ollagi's own (0016), but only Claude's:
the list came from `~/.claude/sessions/*.json`, the file Claude Code keeps for each running session.
omp keeps no such file, so every omp typed into a terminal was invisible. On 2026-11-09 three were
running (two for three days); the page listed none and only said "Also running: N other Claude
process(es)", counting them as Claude. 0037 named the same gap for resume: a terminal omp's open
conversation was still offered, and resuming it would put two omp processes on one file.

## Decision

- `omp_conversations.running()` finds them in `/proc`: a process named `omp` whose parent is not omp
  (that is one of its helpers), that has a controlling terminal, and that holds a conversation file open
  (`/proc/<pid>/fd` → `~/.omp/agent/sessions/<folder>/<time>_<id>.jsonl`). The file's first lines give
  the id, folder and title, as in 0037. A file one folder deeper is a subagent's and has its own
  session line; it is never taken for the session's conversation.
- The controlling terminal comes from `/proc/<pid>/stat`, not from fd 0: omp points its standard input
  at `/dev/null` while it runs a command, so fd 0 would hide a session that is busy. Background runs
  (`omp -p` from a service) and omp's helpers have no controlling terminal.
- `/api/outside` returns both agents (`program` says which). An omp session's conversation is read from
  the file it holds open (prompts, replies, one line per tool call from its short intent, `i`); thinking, tool
  output and omp's own `developer` messages are left out.
- Read only. omp reports no busy or idle outside ollagi (its state hook, 0036, writes only for ollagi's
  sessions), so its status is `unknown`, and Take over refuses any session that is not Claude's: ending
  an omp could cut off a turn in progress, and the reopen is `claude --resume`. The page drops the status
  word and the Take over sentence for omp.
- The sessions folder is compared by its real path: /proc names open files with symlinks resolved, so a
  home folder behind a symlink would otherwise hide every session (and offer their conversations for
  resume again).
- Resume leaves out a conversation a terminal omp has open, as it already did for ollagi's own (0037).

## Consequences

- The three terminal omp sessions show on the page with their titles, a `terminal` and an `omp` tag, age
  and memory, and their conversation opens. The "other agent process(es)" line (renamed from Claude)
  now counts only agent processes that are neither ollagi's nor a session found here: on 2026-11-09 that
  was one omp worker whose parent is named `omp daemon brok…`, which `find_sessions` treats as a root.
- An omp that has not saved its first message holds no file yet and is not listed until it does.
- The page polls `/api/outside`, so `/proc` is walked every few seconds: one `stat` read per process.
- Undo: drop `omp_outside()` from `outside_sessions()` and `resumable()` in `web.py`, and remove
  `running()` and `parse_conversation()` from `omp_conversations.py`.

## Checked

- Tests over a fake `/proc` and invented omp files: a terminal omp is listed with its open conversation
  and start time, also when the sessions folder is reached through a symlink; its helper, a background
  run, a non-omp process, one with no file open and one holding only a subagent's file are not. The
  conversation keeps prompts, replies and tool lines and drops the rest. Page tests: both agents listed,
  an omp conversation read, Take over refused for omp whether it says `unknown` or `idle` with nothing
  ended or reopened, a terminal omp's conversation not offered for resume. Each was seen to fail with its
  part of the code removed. Suite: 289 passed, 1 skipped.
- Live, after restarting `ollagi.service`: `/api/outside` listed the 3 terminal omp sessions (pids 2103,
  2154, 593154) with their titles, `/api/outside/2103/conversation` returned its last 40 items, and a Take
  over POST got 409 "… runs omp, which can be read here but not taken over". In headless Chromium the
  page showed the 3 rows; opening one showed the conversation with no Take over button or sentence.
