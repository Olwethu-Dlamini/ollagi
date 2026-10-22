# 0026: Whole frames to the phone, and WebGL to draw them

Date: 2026-10-22

Follows 0018 (the live terminal) and 0025 (swipe to scroll back).

## Context

On the phone, a Claude session in the live terminal was jittery: the screen tore and jumped while
Claude worked, where the same session in a window on the laptop was calm.

Measured on 2026-10-22 on a working session:

- Claude Code redraws about nine times a second and wraps every redraw in synchronized-update
  marks (`ESC [ ? 2026 h` ... `ESC [ ? 2026 l`): 44 marks in 5 s of its own output. A terminal
  that understands the marks holds the frame and shows it whole.
- tmux passes the marks on only to a terminal whose `terminal-features` include `sync`. The
  laptop's foot advertises it (`client_termfeatures` lists `sync`); the browser's xterm.js calls
  itself `xterm-256color`, and ollagi's tmux.conf listed that name with `RGB` only. A browser-like
  client attached to the session received zero marks in 33 KB of output.
- What reaches a client is about ten chunks a second of 3.5 KB each (121 chunks, 420 KB in 12 s).
  Coalescing them on the server would have merged only 14 %, so the server side was not the cause.
- xterm.js 6.0.0 implements mode 2026: it buffers row refreshes while a mark is open and draws
  the frame on the closing mark, with a 1 s safety timeout.

Two smaller causes on the page itself: the keyboard slides open over several frames and the
ResizeObserver fitted the terminal on each, so every frame resized the session and made Claude
redraw fully; and xterm.js drew with its DOM renderer, which is slow on a phone at ten redraws a
second.

## Decision

- tmux.conf lists `sync` for `xterm-256color`: `set -as terminal-features
  ",foot*:RGB,xterm-256color:RGB:sync"`. A test starts a real tmux server with ollagi's config,
  prints a marked frame in it, and checks that a client attached as xterm-256color receives the
  marks. A terminal that does not know mode 2026 ignores the marks, so nothing else changes.
- The live terminal is fitted once the box has held still for 150 ms (`whenStill` in app.js), not
  on every frame of the keyboard's slide. A pending fit is cancelled when the terminal closes.
- `@xterm/addon-webgl` 0.19.0 (MIT, 126 KB, self-contained) is copied unchanged into `static/`
  like xterm.js itself (0018), loaded together with it, and attached after the terminal opens.
  Without WebGL the DOM renderer stays; if the browser takes the graphics context away, the
  add-on disposes itself and xterm.js falls back.

Considered and not chosen: coalescing pty output on the server before sending it over the
WebSocket. The measurement above shows it would change little, and it would add latency to typing.

## Consequences

- The page's files grow by 126 KB, loaded on the first live terminal only, as before.
- `window-size latest` (0018) still applies: fitting the phone's terminal resizes the session.
  Only the number of resizes changed.
- Undo: remove `:sync` from tmux.conf; remove the add-on file and `drawWithWebgl`; replace
  `whenStill` with a direct `fitter.fit()`.

## Checked

2026-10-22, on the laptop:
- 255 unit tests pass. The new tmux test fails with the old tmux.conf and passes with the new one.
- Headless Chromium 152 at phone size (390 x 844, touch), a throwaway shell session on a test
  server on port 8766, driven over the DevTools protocol: the live terminal opened with a WebGL
  canvas and no fallback warning; the session was sized to the phone (57 x 49); a command typed
  key by key ran in the shell and a marked frame printed in it was shown; the box shrunk in six
  steps 30 ms apart and the session's height stayed at 49 rows throughout and became 24 only once
  the box had settled; no page exceptions.

Not yet checked: on my phone.

## Sources

- Synchronized output (mode 2026): https://gist.github.com/christianparpart/d8a62cc1ab659194337d73e399004036
- tmux `terminal-features`, `sync`: `man tmux`
- @xterm/addon-webgl: https://github.com/xtermjs/xterm.js/tree/master/addons/addon-webgl
