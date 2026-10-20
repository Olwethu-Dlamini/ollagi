# ollagi

A small, self-hosted control room for running Claude Code on my own machine:

- start Claude Code sessions per project and keep them alive in tmux,
- follow and answer them from my phone over Tailscale (open a QR code, no app store app),
- queue tasks to run one after another while I am away,
- group similar tickets so they are solved together in one session,
- never start more work than the machine's RAM can take,
- show and manage the rest of the system too (memory, CPU, disks, heavy processes), with Claude Code as the main focus.

It is built for my SiMedia work first, but nothing in it is tied to SiMedia: projects come from a config file.

## Status

Early. Built in small steps, one idea per commit, so every part can be read and explained.

| Step | What | State |
|------|------|-------|
| 1 | Skeleton, decisions folder | done |
| 2 | `ollagi doctor`: is it safe to start another session? | done |
| 3 | Sessions in tmux: start, list, show, send, stop | done |
| 4 | Web interface: sessions and system, usable on a phone | done |
| 4b | Tailscale: `tailscale serve`, `ollagi qr`, user service | done |
| 5 | RAM watcher: freeze the heaviest session at red, thaw at green | done |
| 5b | Overnight queue, one task at a time | done |
| 5c | Sessions-first page (state dots, menu buttons, colours), after Collie and Codeman | done |
| 6 | Jira: group my open tickets (read only), queue a group as one task | done |
| 6b | Slack outbox: drafts, one approved Send per message | done |
| 7 | Projects from a config file | done |
| 8 | `claude` in a terminal starts through ollagi (`ollagi here`) | done |
| 8b | See sessions started in a terminal, take an idle one over | done |
| 8c | A session as a window on the laptop: opens on start, open/close button, `ollagi open/close` | done |
| 8d | Live: the session as a real terminal in the page (xterm.js over a WebSocket) | done |
| 9 | Summary: a session's screen summarised by Haiku, only on request | done |
| 9a | The session as a chat (Chat and Term tabs), voice into the message box, fits above the keyboard | done |
| 9b | Installable app on the phone (needs HTTPS for the tailnet) | next |
| 9c | Phone notifications through Web Push: needs you, finished, usage limit (needs HTTPS) | next |

## Try it

```bash
uv sync               # create .venv with the pinned versions
uv run ollagi doctor  # is there room for another Claude session?
uv run pytest         # run the tests
uv run ollagi serve   # the web page on http://127.0.0.1:8765 (or run it as a service, below)
uv run ollagi qr      # the phone address as a QR code
```

Phone access, once (decision 0007):

```bash
systemctl --user enable --now "$PWD/deploy/ollagi.service"   # page starts at login
sudo tailscale set --operator=$USER                            # lets tailscale serve run without sudo
tailscale serve --bg --http=80 http://127.0.0.1:8765           # page on http://<machine>.<tailnet>.ts.net
```

`ollagi doctor` on this laptop, 2026-10-19 12:15 (two sessions already open):

```
memory    5.3 GiB available of 11.4 GiB
swap      1.6 GiB used of 22.8 GiB (not counted as available)
cpu load  1.84 (1 min), 2.22 (5 min) on 8 threads
sessions  2 running
          pid 273043: 308 MiB across 1 processes
          pid 275800: 440 MiB across 5 processes
start another? yes: 1 more can start
          5.3 GiB available, minus 1.5 GiB kept free, minus 2.3 GiB growth room for 2 running session(s), leaves 1.5 GiB; each new session needs 1.5 GiB
(exit status 0)
```

## How to read this repo

- `docs/decisions/`: one short note per choice: what was decided, why, and what else was considered. Read these first.
- `docs/suggestions.md`: ideas not decided yet, with what each would change and how to undo it.
- `docs/learning/`: the concepts the code relies on (tmux, Tailscale, `/proc/meminfo`, systemd), explained in plain words.
- `src/ollagi/`: the code. Each module does one job.
- `tests/`: how each job is checked.

## Prior art

Other people solved parts of this already, and their designs shaped this one:
[Codeman](https://github.com/Hugo-DDT/Codeman), [Collie](https://github.com/AltanS/collie),
[Agent of Empires](https://github.com/agent-of-empires/agent-of-empires).
See `docs/decisions/0001-build-our-own.md` for why this is not one of them.
