# ollagi

A small, self-hosted control room for running Claude Code on my own machine:

- start Claude Code sessions per project and keep them alive in tmux,
- follow and answer them from my phone over Tailscale (open a QR code, no app store app),
- queue tasks to run one after another while I am away,
- group similar tickets so they are solved together in one session,
- never start more work than the machine's RAM can take.

It is built for my SiMedia work first, but nothing in it is tied to SiMedia: projects come from a config file.

## Status

Early. Built in small steps, one idea per commit, so every part can be read and explained.

| Step | What | State |
|------|------|-------|
| 1 | Skeleton, decisions folder | done |
| 2 | `ollagi doctor`: is it safe to start another session? | done |
| 3 | Sessions in tmux: start, list, stop | planned |
| 4 | Phone page over `tailscale serve`, `ollagi qr` | planned |
| 5 | Overnight queue, one task at a time | planned |
| 6 | Ticket batching from Jira | planned |
| 7 | Projects from a config file | planned |

## Try it

```bash
uv sync               # create .venv with the pinned versions
uv run ollagi doctor  # is there room for another Claude session?
uv run pytest         # run the tests
```

`ollagi doctor` on this laptop, 2026-10-19 (two sessions already open):

```
memory    4.3 GiB available of 11.4 GiB
swap      1.8 GiB used of 22.8 GiB (not counted as available)
cpu load  2.51 (1 min), 2.56 (5 min) on 8 threads
sessions  2 running
          pid 273043: 341 MiB across 3 processes
          pid 275800: 422 MiB across 4 processes
start another? no: 0 more can start
          2 sessions running, the limit is 2
```

## How to read this repo

- `docs/decisions/`: one short note per choice: what was decided, why, and what else was considered. Read these first.
- `docs/learning/`: the concepts the code relies on (tmux, Tailscale, `/proc/meminfo`, systemd), explained in plain words.
- `src/ollagi/`: the code. Each module does one job.
- `tests/`: how each job is checked.

## Prior art

Other people solved parts of this already, and their designs shaped this one:
[Codeman](https://github.com/Hugo-DDT/Codeman), [Collie](https://github.com/AltanS/collie),
[Agent of Empires](https://github.com/agent-of-empires/agent-of-empires).
See `docs/decisions/0001-build-our-own.md` for why this is not one of them.
