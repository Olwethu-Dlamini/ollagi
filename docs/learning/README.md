# Concepts ollagi relies on

Short explanations, added as each step needs them. If a term in the code is unclear, it should be here.

## Decision records (`docs/decisions/`)

A decision record is a short note written when a choice is made: the situation, what was chosen,
why, and what it costs. Code shows *what* the system does; decision records keep *why*, which is
the part that gets lost. Each one is numbered and never rewritten: if a decision changes, a new
record says so and points back to the old one.

## The Python project layout

- `pyproject.toml` is the project's identity card: its name, version, the Python it needs, its
  dependencies, and `[project.scripts]`, which says "the command `ollagi` runs `main()` in
  `ollagi.cli`".
- `uv sync` reads it, creates `.venv/` (a private copy of Python plus our packages, so nothing is
  installed system-wide) and writes `uv.lock` with the exact version of every package.
- `uv run <cmd>` runs a command inside that environment, for example `uv run pytest` or
  `uv run ollagi --help`.
- `src/ollagi/` is the package. `tests/` holds tests that pytest finds by their `test_` prefix.
