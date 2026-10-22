# 0027: A plain terminal from the phone

Date: 2026-10-22

Follows 0018, which considered a shell session started from the page and did not choose it.

## Context

From the phone, the only thing the page could start was Claude. A shell for a quick `git status`,
a test run or a look at a log meant opening a Claude session and asking it, or the laptop. 0018
left the shell out because `ollagi start NAME DIR -- bash` already gave one from the terminal, which
is no help on the phone.

## Decision

- `POST /api/sessions` takes `"program": "claude"` (as before) or `"shell"`. A shell session
  runs my login shell from the password database (the service has no `SHELL` in its environment)
  in the chosen folder, in tmux like any session, so it shows on the page and in the live terminal.
- The budget (0003, made for Claude's 1.5 GiB) is not asked for a shell: a settled shell session
  is 4 MiB (anon, measured in its slice). Anything other than the two words is refused.
- A session's record saves what it runs (`"program"`: `claude`, or the shell's name, `bash`), and
  `info()` reports it for every session.
- The notifier leaves out any session whose program is not `claude`: a shell never needs me, and a
  program in it could draw something that reads like a Claude menu.
- On the page the sheet is "New session" with Start Claude and Start a terminal; the button that
  sends the form decides. In the list a shell session shows its program as a tag after the name,
  like the "terminal" tag of 0016, and its line under the name has no Claude state, only age and
  memory, because the states (0010) are read from Claude's screen.
- `ollagi start --shell NAME DIR` does the same from the command line.

## Consequences

- A shell started from the page opens a window on the laptop too when `open_on_start` is on
  (0017), like any session; Close on laptop puts it away.
- The screen reader (0010) still runs on a shell session for the page's dot, which is usually
  "unknown" (hollow). The notifier does not see it.
- Undo: remove the `program` field from `StartRequest` and the second button; the record's
  `program` key is harmless.

## Checked

2026-10-22, on the laptop: 255 unit tests. In headless Chromium at phone size against a test
server: Start a terminal from the sheet created a session the API listed with program `bash`, tmux
ran `bash` in it, the list row carried the `bash` tag with "0s · 95 MiB" under it (the 95 MiB is
the first seconds, while the shell's start-up files run; 4 s later the slice held 3.7 MiB anon),
the live terminal opened on it and a typed command ran in it.

Not yet checked: on my phone.
