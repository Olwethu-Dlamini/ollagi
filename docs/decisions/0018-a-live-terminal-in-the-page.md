# 0018: A live terminal in the page

Date: 2026-10-20

## Context

The page shows a session by reading its screen every 1.5 s (`tmux capture-pane`) and types through
`send-keys`, with buttons for the keys a phone lacks. That works for answering Claude, but it is not
a terminal: arrows, Esc and menus need buttons, and what I see is up to 1.5 s old. From the phone I
want the session as it is on the laptop, without spending laptop memory on it.

Measured on the laptop before choosing (2026-10-20): a `claude` process 185 MiB on average (8
running), a foot window about 25 MiB, a tmux server about 5 MiB, bash 4.5 MiB.

## Decision

- The session view gets a **Live** button. It replaces the polled screen with xterm.js, a terminal
  drawn in the browser. On the laptop, the server runs `tmux attach` for the session in a
  pseudo-terminal (pty) and passes its bytes over a WebSocket (`/api/sessions/{name}/terminal`).
  Pressing Live again, leaving the session or closing the page ends that `tmux attach` only: the
  session keeps running.
- The page sends JSON messages only: typing (`input`) or a size (`resize`, at most 300 x 500). The
  server sends raw output. Nothing else is accepted.
- The program runs through `setsid -c`, so the pty is its controlling terminal: only then does the
  kernel send it SIGWINCH when the size changes, which makes tmux redraw at the new size.
- **Who may open one.** The access middleware sees HTTP requests only, and browsers open WebSockets
  without a preflight, so the `X-Ollagi` header proves nothing here. The route checks host and
  Tailscale login itself, and also `Origin`: the browser sets it to the page that asked, and a
  website cannot change it. A terminal opens only when Origin matches Host (`access.check_terminal`).
- **Not a laptop window.** The browser's `tmux attach` carries `OLLAGI_VIEWER=browser` in its
  environment. Counting and closing laptop windows (0017) reads `/proc/<client pid>/environ` and
  leaves it out, so "Close on laptop" and `ollagi close` detach real windows one by one, by tty,
  instead of every client at once (this replaces the `detach-client -s main` of 0017).
- xterm.js 6.0.0 and its fit add-on (MIT) are copied unchanged into `static/`, with their license
  in `xterm-LICENSE.txt`. No CDN: the page works without the internet, and nothing outside the
  laptop sees which sessions I open. They load on the first press of Live only (about 350 KB).
- While live, the page still asks for the screen, but every 4 s instead of 1.5 s, for the state
  dot, the laptop button and the menu buttons. The Keys, Quick and reply box keep working.
- `wsproto` is added: uvicorn needs a WebSocket library, and it is small and pure Python.

Considered and not chosen: a plain shell session (bash) started from the page. It costs about
10 MiB while it runs, against about 5 MiB only while a live view is open, and a live terminal on a
bash session already gives the shell (`ollagi start NAME DIR -- bash`).

## Consequences

- One live view costs one tmux client on the laptop: 5.2 MiB measured. xterm.js runs on the phone.
- tmux sizes a session to whoever typed last (`window-size latest`). Typing on the phone narrows
  the session, including its window on the laptop; typing on the laptop widens it again.
- A frozen session refuses a terminal (its tmux is paused); freezing one while live closes the view.
- Over plain `http://`, the bytes between phone and laptop are encrypted by Tailscale (WireGuard),
  not by the page. HTTPS for the tailnet is still the next step.

## RAM, measured

Question: does Live use more RAM on the laptop than the plain view? Yes, about 5 MiB, and only
while it is open. Nothing stays behind when it closes.

Measured 2026-10-20 on a throwaway `bash` session, page driven by headless Chromium at phone size
(the browser itself runs outside ollagi and is not counted; on the phone it is the phone's memory).
"Service" is everything in `ollagi.service`: the server and the `tmux attach` it starts for Live,
summed RSS. "Session" is the session's slice, `anon` from `memory.stat`.

- No page open: service 54.1 MiB, session 3.7 MiB, no tmux client.
- Plain view open, 20 s: service 54.7 MiB (+0.6), session 3.7 MiB.
- Live open, 20 s: service 60.0 MiB (+5.3: the one `tmux: client` process), session 3.7 MiB.
- Live, after printing 200,000 lines: service 60.1 MiB, session 9.5 MiB. The session grows because
  tmux keeps up to 50,000 lines of scrollback (`history-limit`); the same output grows it as much
  without Live, and the limit caps it.
- Live off: service 54.9 MiB, no client left, session unchanged.

For comparison: a laptop window (0017) is about 31 MiB, a Claude session 185 to 380 MiB.

The server creeps up while any session view is open, with or without Live: 25 Live on/off rounds
took it from 54.9 to 59.7 MiB, and then 150 s of the plain view alone took it from 59.7 to
63.1 MiB, in steps of about 2 MiB. With no page open it stayed flat (41.0 MiB `anon` before and
after). So that creep belongs to the page's screen reading, not to Live. Whether it levels off is
not measured yet.

## Checked

On the laptop, 2026-10-20, with a throwaway `bash` session (`livetest`), headless Chromium, first on
a test server on port 8766 (watcher and queue off), then through the restarted service and the
tailnet address:
- typing `echo LIVE-$((6*7))`, Enter, then Up and Enter: the line ran twice in the session
  (`tmux capture-pane`) and was drawn twice in the browser;
- one client attached, TERM `xterm-256color`, 5.2 MiB; the page reported 0 laptop windows;
- at 1200 x 800 the session was 152 x 34; at a phone-sized 390 x 844 it became 48 x 35, and
  `stty size` inside said `35 48`;
- Live off: plain view back, no client left, the session still running; no page errors;
- a WebSocket upgrade with `Origin: https://evil.example` got 403, with the page's own origin 101.

On my phone through the tailnet, 2026-10-20: Live opened and the touch keyboard typed into the
session without trouble.
