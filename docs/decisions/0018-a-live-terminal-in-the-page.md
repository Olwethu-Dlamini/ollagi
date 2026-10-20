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

Not yet checked: a real phone (touch keyboard).
