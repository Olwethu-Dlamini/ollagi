# 0035: Sessions can run agents other than Claude Code

Date: 2026-10-26

## Context

ollagi was built around one agent: every session ran `claude`, its state came from Claude's screen, and
the overnight queue ran `claude "<prompt>"`. I now also work in omp (a different coding-agent harness
that runs the same Claude models, and others). I want the same control room for both, and room for
Codex later, without a second copy of ollagi to maintain.

## Decision

- `src/ollagi/agents.py` describes each agent by what ollagi needs from it: its program, how a first
  message is passed (`claude "<prompt>"`, `omp "<prompt>"`), how a conversation is resumed
  (`--resume ID` for both), and its process name in /proc (`claude`, `omp`).
- The config chooses: `agent = "omp"` at the top for every new session, and an optional `agent` per
  project to override it. Claude stays the default, so a config without the key behaves as before.
- A typo (`agent = "opm"`) is refused when the file is read, not when a session would start at 2 am.
- `/api/system` reports, for each project, the agent a new session there would run.

This step only adds the description and the choice. Starting, watching and resuming an omp session
follow in the next steps (0036 onwards).

## Consequences

- One repo, one page, several agents. Each agent still needs its own way of telling ollagi what state
  it is in (Claude: its screen; omp: decision 0036).
- Undo: remove `agents.py` and the `agent` keys; nothing else reads them yet.

## Checked

2026-10-26: `tests/test_agents.py` (5 tests) and the whole suite: 262 passed, 3 skipped.
