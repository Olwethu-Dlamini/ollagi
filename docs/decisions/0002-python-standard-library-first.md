# 0002: Python, standard library first, uv for the environment

Date: 2026-10-19

## Context

ollagi mostly reads system files (`/proc/meminfo`), runs other programs (`tmux`, `claude`,
`tailscale`) and later serves a small web page. I already use Python at work (chat-service) and
need to explain every line.

## Decision

- Python 3.12 or newer.
- Use the standard library until a step clearly needs more: `argparse` for the command line,
  `subprocess` to run tmux, `sqlite3` for the queue. Add a package only with its own decision note.
- `uv` creates the virtual environment and pins exact versions in `uv.lock`, which is committed so
  every machine installs the same thing.
- `src/` layout: the code lives in `src/ollagi/`, so tests import the installed package, not files
  that merely happen to sit next to them.
- `pytest` for tests (a dev-only dependency; it is not installed for normal use).

## Why

- Fewer dependencies means less to learn, less to download (my data is metered), and less to break.
- The standard library is documented in one place and will not disappear.

## Considered

- TypeScript with Node or Bun, as Collie and Codeman use: it matches Admin-Frontend, but it adds a
  build step and a second language for a tool that is mostly system calls.
- Click or Typer for the command line: nicer help output, but argparse is enough and already there.
