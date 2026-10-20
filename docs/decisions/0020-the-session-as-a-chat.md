# 0020: The session as a chat, with voice

Date: 2026-10-20

## Context

On the phone, the session view stacked a header, a row of session chips, the screen, the "Claude is
asking" card, two rows of keys and the reply box. With the phone keyboard open, the screen was left
with a strip about 70 px tall (measured at 390 x 500, the space a keyboard leaves). I asked for
something like a team chat app instead, and for voice.

The plain screen also looked skewed on the phone: a session is 200 columns wide, and the page
wrapped every long line at a word, so Claude's boxes broke apart and right-aligned text moved to
the next line (reproduced on a 200-column sample screen at 390 px).

## Decision

- The session view has two tabs, **Chat** (the default) and **Term**.
- **Chat** shows the conversation from Claude's own files, read every 2.5 s, no tokens: Claude on
  the left, me on the right, tool steps in a row folded into one grey line that opens on a tap, a
  question as a card with one button per choice, and the session's state under the last message.
  Claude's ``` blocks, `code` and **bold** are drawn from elements, never HTML.
- The Claude in a session is the program tmux started: the pane's process id leads to Claude's
  session file (`~/.claude/sessions/<pid>.json`) and from there to the conversation
  (`GET /api/sessions/{name}/conversation`, read only). Before its first question ("trust this
  folder?") is answered, Claude has written no session file yet; it is then recognised by its
  process name. A session running something else (bash) opens on Term.
- Claude Code's bookkeeping in the conversation file is shown as a person would read it: a slash
  command as `/name args`, a shell line as `! command`, their output as one short line, pasted text
  as `[pasted text]`; caveats, background task notices and skill context are left out.
- **Term** shows the screen without wrapping: every line as Claude drew it, left-aligned, the wide
  ones scrolling sideways; padding spaces at line ends are dropped. **Live** (0018) is in its bar.
  The keys a phone lacks are one row above the message box, swiped sideways.
- One composer: **+** opens a sheet with all keys, quick replies and the summary (0019); the
  message box with a **microphone**; send.
- **Voice** uses the browser's speech recognition. Spoken words land in the message box to read and
  send with the send button; nothing is sent by voice alone. Chrome turns speech into text with
  Google's speech service. Browsers allow the microphone only on `https://` pages (and on the laptop
  itself), so until the tailnet has HTTPS the button says so and points to the keyboard's own
  microphone key, which works already.
- When the phone keyboard opens, the page shrinks to the space above it (the viewport setting
  `interactive-widget=resizes-content`, and the visible area followed by hand where a browser does
  not), and a question shrinks to its buttons in one row.

Considered and not chosen: keeping the screen-first layout with a slimmer header and one key row.
It fixed the space, but a chat is how I already read Claude, and it needs no terminal reading.

## Consequences

- The chat is only as good as Claude Code's internal files (seen in 2.1.280, not a published
  format). If they change, the chat can go empty while Term still works.
- A question whose choices are not numbered (the folder trust question) gets no buttons: the state
  detection (0010) only knows numbered menus. Term's arrow and Enter keys answer it.
- With the keyboard open, the chat keeps 383 of 500 px (measured), against about 70 before.

## Checked

2026-10-20, headless Chromium at 390 x 844, first on a test server (port 8766, watcher and queue
off), then through the restarted service and the tailnet address:
- a throwaway Claude session on Haiku with no settings (`chattest`): at its trust question the chat
  said "No messages yet" instead of moving to Term; the question was answered from Term's key row
  (down, Enter); a stand-in for speech recognition (headless has no microphone) put
  "reply with only the word PONG" in the box, and nothing reached the session before send; after
  send the chat showed my bubble and Claude's "PONG", state "done";
- at 390 x 500 (keyboard open) the composer sat at the bottom edge and the chat kept 383 px;
- the + sheet showed 12 keys, 5 quick replies and Summarise;
- a 200-column bash screen in Term: `white-space: pre`, the box intact, the status line not wrapped;
- through the tailnet (`http://`, not a secure context): the microphone showed its explanation;
  Live opened inside Term; one of my real sessions' chats was opened read only (5 of my messages,
  21 of Claude's, 20 folded step groups, scrolled to the end) with no request that changes anything;
- 40 of my real conversation files: no message left starting with a tag; 216 unit tests pass.

Not yet checked: on my phone.
