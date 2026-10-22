# 0034: The session list is not redrawn behind an open session

Date: 2026-10-22

## Context

Every 4 s the page fetched the lists and rebuilt the sessions screen, under the open session that
covers it: DOM work the phone never saw.

## Decision

`renderSessions` returns at once while a session is open. The lists are still fetched (the
session's header and the switcher read them); closing the session draws the list fresh.

## Consequences

- Undo: one condition.

## Checked

2026-10-22: headless Chromium: no rows were built while a session was open; rows appeared within a
second of closing it.
