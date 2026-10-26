# 0038: A view frozen at the live screen comes back by itself; the live poll leaves the screen out

Date: 2026-10-26

## Context

On the first day using ollagi from the phone, it "felt slow". Measured first: every endpoint answers in
under 70 ms over the tailnet, the page loads in about 1 s with a phone's CPU (4x throttled), and 20 s
inside an open session cost 0.8 s of CPU with no long tasks. Two things were wrong instead:

- The session sat in tmux's copy mode (scroll mode) at the bottom of its history. Copy mode freezes the
  view for every client attached, so phone and laptop both stopped following the agent while it worked.
  A wheel or swipe enters copy mode with `-e` and leaves it at the bottom, but other ways in (a mouse
  selection) enter without `-e`, and then nothing left it.
- With the live terminal open, the page still fetched the 300-line coloured screen every 4 s (46 KB for
  that session) only to read the state dot and a question's buttons: about 690 KB a minute.

## Decision

- `tmux.conf`: in copy mode, a wheel turned down at the bottom always leaves it, however it was entered.
- `sessions.leave_frozen_bottom`: when the page opens a live terminal, a session in copy mode at the
  bottom is released. A session scrolled up to read is left where it is.
- `GET /api/sessions/{name}/screen?text=0` returns the state, question and choices without the screen.
  The page asks that way while its live terminal is open. Claude's screen is still read on the server
  (its state comes from it); omp's is not captured at all.

## Consequences

- Opening a session on the phone, or swiping down at the bottom, always shows the agent live again.
- The live poll is about 130 bytes instead of tens of KB.
- Settings in `tmux.conf` reach a session's tmux server when it starts; a running one needs
  `tmux -L ollagi-<name> source-file src/ollagi/tmux.conf` (done for g6-close-out on 2026-10-26).
- Undo: drop the copy-mode binding, the `leave_frozen_bottom` call in the terminal endpoint, and `&text=0`
  in `app.js`.

## Checked

- `test_a_view_frozen_at_the_live_screen_comes_back_live` drives a real tmux and a real attached
  terminal: it failed before the binding (the wheel at the bottom left copy mode in place), and checks
  that a reader scrolled up is not yanked.
- `test_with_the_live_terminal_open_the_page_gets_the_state_and_question_without_the_screen` failed
  before `text=0` existed (the screen came back).
- Live, phone-sized Brave over the tailnet: a scratch session put in copy mode at the bottom showed
  `pane_in_mode=1`; after the page opened it, `0`. The screen polls after the first were 132-135 bytes.
- Not the cause, ruled out: the tmux window size (attach and resize both make the phone the size
  owner; a cut-off screenshot came from changing the emulated pixel ratio on an open page).
