# 0031: One scratch shell per folder

Date: 2026-10-22

Follows 0027 (a plain terminal from the phone).

## Context

Start a terminal is for a quick look: `git status`, a test run, a log. A second tap for the same
folder, a minute later, should not make a second shell.

## Decision

Start a terminal for a folder that already has a running, unfrozen shell session hands that
session back (`"started": NAME, "reused": true`) and the page opens it. Each folder still gets its
own. A frozen or exited shell is not reused.

## Consequences

- To have two shells in one folder, use `ollagi start --shell` with a name, or stop the first.
- Undo: remove the loop at the top of the shell branch in `start_session`.

## Checked

2026-10-22: 260 unit tests. Headless Chromium: a second Start a terminal for /tmp opened the
first shell again; the API listed one shell session for the folder.
