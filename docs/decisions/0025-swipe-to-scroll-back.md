# 0025: Swipe to scroll back in the live terminal

Date: 2026-10-21

Follows 0018 (the live terminal) and 0021 (sessions open in it by default).

## Context

On the phone, a session opens in its live terminal, and a swipe did not scroll back to earlier
output. The history is not in the page's terminal: tmux on the laptop keeps it (up to 50,000 lines,
`history-limit`), and the page's xterm.js only shows the current screen. tmux scrolls when it gets
mouse-wheel events (`mouse on` in tmux.conf), and xterm.js forwards a wheel to it, which is why the
laptop's mouse wheel works. xterm.js does not turn a finger swipe into a wheel. Claude Code itself
does not take mouse events (`mouse_any_flag` 0 on my sessions), so wheel events reach tmux.

A second problem appears once scrolling works: scrolled back, tmux is in copy mode and reads keys
as scroll commands, so a message typed from the page would be lost.

## Decision

- **The page turns a vertical swipe into wheel events** on the live terminal (`swipeToScroll` in
  app.js), one per five lines of finger travel, since tmux scrolls five lines per wheel. Finger
  moving down shows older lines, like any list on a phone; swiping back to the bottom ends copy mode
  (tmux's `copy-mode -e`), back to the live screen. Moves under 8 pixels are taps and are left to
  xterm.js (focus, keyboard); sideways moves are left to the page.
- **Typing returns to the live screen first.** Every `send_text` and `send_key` (the message box,
  the keys row, answer buttons) first runs `tmux if-shell -F '#{pane_in_mode}' 'send-keys -X cancel'`,
  which does nothing unless the pane is scrolled. In the live terminal, after a swipe up the page
  sends `{"type": "bottom"}` before the next key; the server runs the same command and finishes it
  before reading the key.
- Wheel events travel to the server the same way as keys (as `ESC [ < 64;x;y M` "mouse reports"),
  so the page tells them apart; otherwise every wheel event would count as typing and undo the
  scroll.

The other choice was a server route that scrolls tmux directly (`copy-mode` plus `scroll-up`). The
wheel route needs no new server code for scrolling and behaves exactly like the laptop's wheel.

## Consequences

- Scrolling is tmux's copy mode, shown inside the terminal: tmux draws its position, such as
  `[40/7859]`, at the top right.
- Each swipe step scrolls five lines; a long session needs long or repeated swipes. The copy of the
  screen (⋯ menu) still scrolls natively, through its last 200 lines.
- Undo: remove `swipeToScroll` from app.js; the server-side return to the live screen is worth
  keeping, as a mouse wheel on the laptop can leave a session scrolled back too.

## Checked

2026-10-21:
- 249 unit tests. A real tmux session put in copy mode lost typed text before the change and
  receives it after (`test_a_real_session_starts_shows_output_takes_input_and_stops`); the WebSocket
  test checks that "bottom" reaches the session before the next key.
- Headless Chromium at phone size with touch, a throwaway `bash` session with 300 lines of output,
  test server on port 8766: a swipe scrolled 15 lines and a longer one 40; swiping back returned to
  the live screen; typing after a swipe reached bash; a tap did not scroll. The first try showed
  scroll position 0 after every swipe: each wheel report counted as typing and sent "bottom". Fixed
  before committing.

Not yet checked: on my phone.

The full guide is `docs/guides/scrolling-back-on-the-phone.md`.

## Sources

- tmux copy mode, `mouse`, `history-limit`, `WheelUpPane`: `man tmux`
- xterm.js mouse reporting (SGR 1006 format): https://xtermjs.org/docs/
- Touch events: https://developer.mozilla.org/en-US/docs/Web/API/Touch_events
