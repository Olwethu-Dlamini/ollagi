# Guide: scrolling back in a session on the phone

How to read earlier output of a Claude session on the phone, why it needed work, how it works, how it
was tested, and the questions people ask. The short record is `docs/decisions/0025`.

## 1. What it does

In a session's live terminal (the default view since decision 0021):

- **Swipe down** (finger moving down) to see older output, as in any list on a phone.
- **Swipe up** to go back towards the newest lines. At the bottom you are back on the live screen.
- **Type anything** (the message box, the keys row, an answer button, or the terminal keyboard) and
  the session first returns to the live screen, so what you type reaches Claude.
- **Taps** still focus the terminal and open the keyboard; they never scroll.

While scrolled back, tmux shows the position at the top right, for example `[40/7859]`: 40 lines up
of 7,859 kept.

The copy of the screen (⋯ menu → Show a copy of the screen) is another way to read back: a plain
page of the last 200 lines that scrolls like any page.

## 2. Why it did not scroll before

```
phone: xterm.js (shows only the current screen)  <-- WebSocket -->  tmux attach  <-->  tmux (keeps the history)
```

- The page's terminal is a window onto tmux; it holds only what is on screen now. The earlier output
  is kept by tmux on the laptop, up to 50,000 lines (`history-limit` in `src/ollagi/tmux.conf`).
- tmux scrolls when it receives mouse-wheel events (`set -g mouse on`). On the laptop, the mouse
  wheel in the terminal sends those, so scrolling works there.
- In the page, xterm.js forwards a mouse wheel to tmux but does nothing with a finger, so on the
  phone a swipe had nothing to scroll.

## 3. How it works

### 3.1 A swipe becomes wheel events (page, `swipeToScroll` in `static/app.js`)

1. On `touchstart` the page remembers where the finger is.
2. On `touchmove` it adds up the vertical distance. Under 8 pixels it is still a possible tap and
   nothing happens.
3. Past that it is a swipe: the page stops the browser from scrolling or bouncing the page, and for
   every five lines of travel (five times the height of one terminal line) it hands xterm.js a wheel
   event. Five, because tmux scrolls five lines per wheel event.
4. xterm.js encodes each as a mouse report, `ESC [ < 64 ; x ; y M` (64 = wheel up, 65 = wheel down),
   and sends it over the WebSocket to `tmux attach`, exactly as for a real wheel.
5. tmux receives the first wheel-up and enters **copy mode** (its scroll mode); each further one
   scrolls five lines. Reaching the bottom ends copy mode by itself (tmux's `copy-mode -e`).

### 3.2 Typing returns to the live screen (server, `sessions.leave_scrollback`)

In copy mode tmux reads keys as scroll commands, so typed text would be lost. Two paths, one command:

- **Message box, keys row, answer buttons** go through `send_text` / `send_key`, which now first run:

  ```
  tmux if-shell -F -t main '#{pane_in_mode}' 'send-keys -t main -X cancel'
  ```

  `#{pane_in_mode}` is 1 only while scrolled; then `cancel` leaves copy mode. Otherwise it does nothing.
- **The live terminal's own keyboard**: after a swipe up the page remembers it is scrolled back, and
  before the next key sends `{"type": "bottom"}` over the WebSocket. The server runs the same
  command and waits for it before passing on the key (`terminal.relay`, `to_bottom`).

The wheel events of a swipe travel the same way as keys, so the page tells them apart by their shape
(`MOUSE_REPORT` in app.js). Without that, every wheel event would count as typing and undo the
scroll; that was the bug the first headless test found.

### 3.3 The files

| File | Change |
|------|--------|
| `src/ollagi/static/app.js` | `swipeToScroll`, `MOUSE_REPORT`, "bottom" before the next key |
| `src/ollagi/terminal.py` | the `{"type": "bottom"}` message and `relay(..., to_bottom=...)` |
| `src/ollagi/sessions.py` | `leave_scrollback`, called first by `send_text` and `send_key` |
| `src/ollagi/web.py` | passes `leave_scrollback` for the session to the live terminal |

## 4. How it was tested

- **Unit tests** (249 in all): the exact tmux command, run before every send; "bottom" accepted as a
  message and anything else still refused; through the WebSocket, "bottom" reaches the session
  before the next key.
- **A real tmux session**: put in copy mode, then sent text. Before the change the text was lost
  (the test failed); after it, the text arrives.
- **Headless Chromium at phone size with touch**, a throwaway `bash` session with 300 lines:
  swipe down scrolled 15 lines, a longer swipe 40; swiping back up returned to the live screen;
  scrolling again and typing reached bash; a tap did not scroll.
- Read-only check on my running Claude sessions: Claude does not take mouse events
  (`mouse_any_flag` 0) and the history is in tmux (`history_size` 7,859 on one), so wheel events
  reach tmux and have something to scroll.

## 5. Troubleshooting

| What I see | Why | What to do |
|------------|-----|------------|
| Swiping does nothing | The page still runs an old app.js | Close ollagi fully and open it again (the server sends no-cache since 32b04f3) |
| Swiping scrolls the whole page instead | The swipe started outside the terminal (on the title bar or the keys row) | Start the swipe on the terminal itself |
| It scrolls only a little per swipe | Five lines per step; a long session has thousands | Swipe longer, or use the copy of the screen |
| The screen stays scrolled and does not update | It is in copy mode, frozen at that point | Swipe up to the bottom, or type anything |
| A key did something odd while scrolled | A key reached tmux's copy mode before the page sent "bottom" | Report it; the page sends "bottom" before every key after a swipe up |

## 6. Questions people ask

**Why not just keep the history in the page's terminal?** The page attaches to tmux, which redraws
only the screen; and the page opens fresh every time, while tmux has kept everything since the
session started. Asking tmux is the one place that always has all of it.

**Why five lines per step?** That is what tmux scrolls per wheel event by default. Matching it keeps
the content under the finger moving at about the finger's speed.

**Does scrolling on the phone scroll the laptop's window too?** Yes. Copy mode belongs to the
session's pane, which every window on it shares. Typing anywhere, or reaching the bottom, ends it
for all of them.

**Could it scroll forever?** Back to tmux's limit of 50,000 lines per session.

**Does it cost tokens?** No. It is tmux and the browser only.

## 7. Commits

| Commit | What |
|--------|------|
| `b1d5312` | Return to the live screen before typing into a scrolled-back session |
| `b6c6414` | Swipe to scroll back in a session's live terminal |
