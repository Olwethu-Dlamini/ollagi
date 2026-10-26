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

- Starting follows the choice: the page sends `"program": "agent"` ("whatever this folder runs"), and
  `ollagi start` and `ollagi here` use the same rule. An agent can still be named outright (`"omp"`,
  `"claude"`). The memory budget applies to every agent; only a plain shell is let through when memory
  is short. A running agent session is never handed back as the folder's scratch shell (0031).
- Resume stays Claude-only until omp's conversations can be listed: a Claude conversation id passed to
  omp would resume nothing.
- Memory: a session's process tree starts at any agent process (`claude`, `omp`), so the budget, the
  system panel and the RAM watcher see omp's builds and tests. omp's helpers (`omp daemon brok…`) are
  not sessions; an agent started by another agent belongs to the outer session.

Watching an omp session's state follows in decision 0036.

## Consequences

- One repo, one page, several agents. Each agent still needs its own way of telling ollagi what state
  it is in (Claude: its screen; omp: decision 0036).
- Undo: remove `agents.py` and the `agent` keys, and put `"claude"` back as the page's program.

## Checked

2026-10-26: `tests/test_agents.py` (5 tests) and 4 page tests in `tests/test_web.py`. Each page test was
run against the code with its rule removed (budget for Claude only; shell reuse keyed on "not claude")
and failed; with the rule back, the whole suite: 266 passed, 3 skipped. Memory: 3 tests in
`tests/test_processes.py`, two of which fail with Claude-only matching; on this laptop `ollagi doctor`
then listed the 3 running omp sessions (202, 766 and 122 MiB) that it did not see before, and answered
"start another? no" (1.3 GiB left, 1.5 needed). Suite: 269 passed, 3 skipped.
