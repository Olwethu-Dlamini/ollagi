# 0021: Claude's screen first, and a plain look

Date: 2026-10-20

Replaces the chat view of 0020. The voice button, the + sheet and fitting above the keyboard stay.

## Context

After a try on the phone, the chat view (0020) hid what I need most: whether Claude is working,
thinking or has stopped. Claude's own screen shows that at a glance. What I had asked for was only
that the screen be left-aligned and look better.

The page also looked made by AI. Lists of such tells (sources below) name: the code font used for
labels and buttons, small spaced-out capital headings, pill "chips", rounded bordered cards inside
rounded bordered cards with the same radius everywhere, a floating glowing button, pulsing dots,
emoji as icons, one bright accent colour, and repeated counts. The page had every one of these.

## Decision

- A session opens as the **live terminal** (0018): Claude's real screen, redrawn for the phone's
  width. A **copy of the screen** (read every 1.5 s, lines left as drawn, wide ones scrolled
  sideways) is one tap away in ⋯; the choice is remembered on the device. The copy is also used
  whenever the live terminal cannot run: a paused session, or one whose terminal closed.
- The chat tab and its route are removed. Reading Claude Code's bookkeeping lines (0020) stays,
  for the sheet of sessions started in a terminal.
- A question on screen becomes **one row of buttons** above the keys, one per choice; the question
  itself is on the screen just above, so it is not repeated.
- The header's state comes from the screen, so its dot and its words agree.
- **The look**, a plain utility like the phone's own Settings or Clock app:
  - the phone's own font (Roboto on Android); the code font only in the terminal;
  - flat lists with thin dividers that start at the text; section headings small, in sentence case;
  - black and white, with colour only for a session's state (red only for "needs you");
  - small line icons drawn the same way (back, more, plus, microphone, send) instead of emoji;
  - no chips, no floating button ("New" is a word in the top bar), no glow, no pulsing; the only
    motion is a button dimming while pressed;
  - small 6 px corners on buttons and fields only;
  - rows say "working · 9h · 1.0 GiB" instead of a folder path; GiB and MiB everywhere, because
    that is what the numbers are.
- Not added, although design guides suggest them to make a page look "designed": glass effects,
  grain, gradients, scroll animations, a display font. Those are AI tells of their own.

## Consequences

- Opening a session on the phone narrows it on the laptop too, while the live terminal is open
  (tmux sizes a session to whoever used it last, 0018). The copy in ⋯ leaves the laptop alone.
- xterm.js (about 350 KB) now loads the first time any session is opened, not only on demand.

## Checked

2026-10-20, headless Chromium at 390 x 844, light and dark, on a test server (port 8766, watcher and
queue off) with a throwaway Claude session on Haiku with no settings (`chattest`):
- the session opened as the live terminal by itself, one tmux client, Claude's screen at the
  phone's width;
- asking it to create a file brought up its permission question; the page showed the buttons
  "1 Yes", "2 Yes, and switch to accept edits…", "3 No" in one row, the header said "needs you"
  with a red dot; pressing 1 answered it and the row went away;
- ⋯ listed "Show a copy of the screen", "Open on laptop", "Pause (freeze)", "Stop session"; the copy
  replaced the live terminal and left no tmux client; switching back opened it again;
- with the keyboard's space taken (390 x 500), the screen kept the space above the keys;
- home, Queue and System in light and dark: no chips, no cards, dividers between rows;
- no page errors; 208 unit tests pass;
- the restarted service serves the new page; my own sessions were left as they were (not opened).

On my phone through the tailnet, 2026-10-21: it works and looks better.

## Sources

- smoothui.dev, "AI Design Slop: Why AI-Generated UI Looks Generic, and the Fix"
- 925studios.co, "AI Slop Web Design: Complete Guide to Spotting and Fixing Generic Websites (2026)"
- paralect.com, "Signs of AI slop in design: 21 patterns that make your site look AI-generated"
- dev.to (GDG), "Why AI Websites All Look the Same and How to Build Something Different"
