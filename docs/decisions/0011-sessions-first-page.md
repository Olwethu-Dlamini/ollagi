# 0011: A sessions-first page, modelled on Collie and Codeman

Date: 2026-10-19

## Context

The first page (0006) put machine cards first and sessions second. Looking at Collie's and Codeman's
screenshots, the useful thing on a phone is "which session needs me", one tap away.

## Decision

- **Home is Sessions**: a summary ("1 needs you · 1 working · 1 done"), project filter chips, and
  sessions grouped by project with a state dot (red needs you, yellow working, green done, hollow
  idle, blue frozen). A session that needs you shows Claude's question in its row and sorts first.
- **System is a second tab**: memory, pressure, watcher, disks and processes; the header keeps only
  small chips (free memory with the watcher's level, CPU load) and a QR button.
- **Session screen**: Claude's own colours (`ansi.js`), a switcher to hop between sessions, a
  "Claude is asking" card that turns a numbered menu into buttons (a tap presses the number, as on
  a keyboard), and a dock with Keys (Esc, Tab, arrows, ^C...) and Quick replies. `/clear` needs a
  second tap within 3 s, because it throws the conversation away.
- The page is now four short files (`index.html`, `style.css`, `ansi.js`, `app.js`) instead of one;
  only those names are served from `/static/`.

States come from `claude_screen.py` (0010). Long rule lines are shortened before drawing, because
Claude draws them as wide as its 200-column window and they would wrap on a phone.

## Checked

Walked at 390x844 with three demo sessions that print real Claude screens from the fixtures (no
tokens): the permission menu became three buttons, tapping 1 delivered the key `1` to the session,
66 coloured runs were drawn, no console errors.
