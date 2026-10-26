# 0036: An omp session's state comes from a hook, not from its screen

Date: 2026-10-26

## Context

The page's state dots, the "needs you" notifications and the overnight queue all need each session's
state. For Claude, ollagi reads the screen (0010): that works, but it is a guess from the shape of lines.
omp is a different program with a different screen, and it has something Claude Code does not: hooks,
small TypeScript files it runs on events (a turn starting, a tool being called, the session ending).

## Decision

- `deploy/omp/ollagi-state.ts`, linked into `~/.omp/agent/hooks/post/`, writes the state to
  `$XDG_RUNTIME_DIR/ollagi/<session>.json` on every change: `idle` when the session opens, `working`
  when a turn starts, `needs_you` with the question and its choices when omp's ask tool runs or a tool
  waits for approval, `working` again once answered, `done` when the turn ends. The file is written then
  renamed, so it is never read half-written, and removed when omp exits.
- It acts only in sessions ollagi started: `sessions.start_command` sets `OLLAGI_SESSION=<name>` on the
  tmux session, and the hook does nothing without a valid name. Subagents are ignored.
- `src/ollagi/omp_state.py` reads the file into the same `Reading` that `claude_screen.read` returns, so
- The overnight queue (0012) starts each task with its folder's agent (`omp "<prompt>"` in an omp
  folder) and follows an omp task through the same hook file: working, waiting with the question,
  done.
  the page and the notifier do not care which agent runs. No file, a damaged file or an unknown state
  reads as `unknown`, never as a guess.
- The notification's Allow and Deny buttons (0029) stay Claude-only: which key picks which choice in
  omp's question is not checked yet, and a wrong key would answer for me. An omp question is answered in
  its own screen in ollagi.

## Consequences

- The state of an omp session is what omp itself says, not a reading of its screen.
- The hook must be installed; without it an omp session shows `unknown`, and nothing worse happens.
- Undo: remove the hook link and the `info.program == "omp"` branch in `web.py`.

## Checked

2026-10-26, with a real omp (18.12.6):

- `omp -p` with the hook: the trace showed `idle`, `working`, `done`, and the file was gone after exit.
- `omp --mode rpc-ui` asked "Approve the plan?" with Approve / Change it: the file said `needs_you`
  with that question and both choices; after answering Approve: `working`, then `done`.
- `omp -p` turns the ask tool off (no screen to ask on), which is why the question was checked in
  rpc-ui mode. In ollagi omp runs interactively in tmux, where the tool is on.
- Tests: `tests/test_omp_state.py` (4), and 2 page tests that each failed with their rule removed (the
  Claude screen reader then reported the screen's question instead of omp's; without the guard a key
  was typed into the omp session). Queue: a test runs an omp task from start to done through the hook's
  states; with the Claude screen reader instead it never counts as working. Suite: 276 passed, 3 skipped.
