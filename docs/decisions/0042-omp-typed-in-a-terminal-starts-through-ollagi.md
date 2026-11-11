# 0042: `omp` typed in a terminal starts through ollagi, like `claude`

Date: 2026-11-11

## Context

I want every session I start on the laptop to be on the phone as well, live, so I can answer it from
either. 0015 did that for Claude: a `claude` shell function sends an interactive chat through
`ollagi here`, which starts it in ollagi's tmux and shows it in the same terminal. Since 0035 omp is my
default agent, and three gaps left every omp I typed outside ollagi:

- there was no `omp` function, only `claude`;
- on this machine (archnox, set up 2026-10-26) `ollagi` was not on the PATH and `~/.bashrc` loaded no
  wrapper, so even `ollagi here` was "command not found";
- `ollagi here` always started the folder's agent from the config, so with `agent = "omp"` a typed
  `claude` would have started omp.

On 2026-11-11 the page listed no ollagi sessions and three terminal omp sessions, read only (0041).

## Decision

- `ollagi here --agent claude|omp` starts that agent; without `--agent` it is still the config's choice.
- `deploy/claude-wrapper.bash` becomes `deploy/agent-wrapper.bash`, with a `claude` and an `omp`
  function sharing one rule (`_ollagi_agent`): through `ollagi here --agent <typed>` only for a person
  starting a chat at a terminal; straight to the real program for no terminal, inside tmux, `OLLAGI_OFF`,
  no `ollagi` installed, a subcommand (`omp git`, `claude mcp`), and options that are not a chat
  (`-p`/`--print`, `--help`, `--version`, and for omp `--mode`, `--export`, `--alias`).
- The subcommand lists are copied from each program's `--help` (claude 2.1.280, omp 18.16.0). A new
  subcommand missing from the list would start a session instead of running; `command omp ...` is the
  way around until the list is updated.
- Installed here: `~/.local/bin/ollagi` links to the worktree's `.venv/bin/ollagi` (the checkout the
  service runs), and `~/.bashrc` sources the wrapper (backup in `~/.bashrc.before-ollagi`).

## Consequences

- An `omp` typed in a new terminal is an ollagi session: on the page and the phone, live and answerable,
  with omp's state hook (0036) reporting idle, working and needs-you. Closing the terminal no longer ends
  it (Ctrl-] then d leaves it; stop it from the page or with `ollagi stop`).
- omp sessions already running in a terminal stay outside ollagi, read only (0041), until they end.
- Undo: remove the line from `~/.bashrc` (or restore the backup) and the `~/.local/bin/ollagi` link.

## Checked

- Tests: `here` starts the config's agent without `--agent` and the named one with it, in both
  directions, and refuses an unknown agent; the wrapper, run by a real bash on a pseudo-terminal with fake
  programs, sends `omp`, `omp 'a prompt' --model x` and `claude --continue` through
  `ollagi here --agent`, and sends print mode, `--mode rpc`, help, version, subcommands, tmux,
  `OLLAGI_OFF` and no terminal straight to the program. Each was seen to fail with its part of the code
  removed (no routing, routing everything, ignoring `--agent`). Suite: 303 passed, 1 skipped.
- Live, on archnox: an interactive `bash -i` loading the real `~/.bashrc`, with a fake `omp` first on the
  PATH, typed `omp 'hello from the laptop'`; the terminal showed it inside ollagi session
  `ollagi-smoke-2b96`, and the running service's `/api/sessions` listed it (program `omp`, folder
  `/tmp/ollagi-smoke`). `ollagi stop` removed it from the list.
