# 0032: A text size for the screen

Date: 2026-10-22

Follows 0021 (Claude's screen first) and 0026 (frames and WebGL).

## Context

At 11 px the phone's live terminal gives about 48 columns, and Claude Code's boxes and columns
break below 80. A smaller font gives more columns at the cost of legibility; the choice is
personal and depends on the phone.

## Decision

The ⋯ menu has "Text size: N px", which cycles through 9, 11, 13 and 15. The phone starts at 11
and the laptop at 13, as before. The size is remembered on the device (localStorage) and applies
to the live terminal, which is refitted so the session gets the new column count, and to the copy
of the screen. It is applied when a session opens.

## Consequences

- Changing the size resizes the session (`window-size latest`, 0018), so Claude redraws once.
- Undo: remove the menu item and `applyFontSize`; the size falls back to 11 or 13.

## Checked

2026-10-22: headless Chromium at phone width: one tap took the label from 11 to 13 px, the copy's
font to 13 px, the session from 57 to 50 columns, and `ollagi.font` to 13 in localStorage. The
first version applied the size at module load, which read a variable declared further down and
stopped the whole module; the headless check caught it (no project list, no form handlers) and it
was fixed before the service restarted.

Not yet checked: on my phone, whether 9 px is readable.
