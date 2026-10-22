# 0029: Allow and Deny on the notification itself

Date: 2026-10-22

Follows 0024 (notifications) and 0028 (urgent notices).

## Context

Most "needs you" notifications are a permission: "Do you want to proceed?" with Yes, Yes-and-don't-
ask-again, No. Answering meant opening the app, waiting for the live terminal, and tapping a
button on the screen, for a plain yes.

## Decision

- A "needs you" notice for a yes-or-no menu carries two buttons (`Notice.actions`): the first
  choice and the first choice whose label starts with "No", each as the number key Claude Code
  takes and a label cut to 24 characters. A phone shows at most two buttons. A menu that is not a
  yes-or-no (a colour to pick, a plan with four ways on) gets none: that needs the screen.
- The notifier's readings carry the menu's options next to the state and question.
- A tap on a button makes the service worker POST `/api/sessions/NAME/answer` with the key and the
  question the notification showed. The server presses the key **only if that question, with that
  choice, is still on the screen**; otherwise nothing is typed and the answer is 409. A
  notification can be minutes old, and a number typed into a session that has moved on would land
  in Claude's prompt box. If it was not answered, a new notification says so and opens the session.

Considered and not chosen: pressing the key without the check (simpler, unsafe); a button for
every choice (phones show two).

## Consequences

- The body is cut to 500 characters (0024), so a long question may be incomplete on the
  notification. Open the session when in doubt.
- Nothing can be answered from the notification while the laptop is unreachable; the follow-up
  notification says "the laptop could not be reached".
- Undo: drop `actions` from `Notice` (the service worker treats a missing list as empty) and the
  `answer` route.

## Checked

2026-10-22, on the laptop: 260 unit tests. Fixtures: the bash and edit permissions give Yes and
No; the trust prompt gives "Yes, I trust this folder" and "No, exit"; the plan menu and the colour
menu give no buttons. The route refuses another question (409), a choice not offered (409) and a
session whose prompt is back (409), and presses the key when the question matches.

Not yet checked: on my phone, a tap on a button of a real notification.
