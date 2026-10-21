# 0024: Notifications on the phone

Date: 2026-10-21

Follows 0022 (HTTPS) and 0023 (the installed app, whose service worker receives them).

## Context

On 2026-10-20 I chose notifications as part of making ollagi smarter: I should not have to keep the
page open to know that a session is waiting for me. On 2026-10-21 I chose which events notify, how
the encryption is done, and to build this together with 0023.

## Decision

**What notifies** (all four offered):
- a session starts asking something (a numbered menu: permission, question, plan approval):
  "api needs you", with the question as the text;
- a session's turn ends after it was working: "api finished";
- the queue reports a task done, waiting for me, failed, unable to start, or stopped by a usage
  limit;
- the RAM watcher pauses, stops or resumes a session.

**How sessions are watched**: the server reads every session's state every 5 seconds, the same
reading the page shows (`claude_screen.py`). A state counts after two reads in a row, so a spinner
that vanishes for a moment between tool calls (with an older "✻ Worked for 3s" still on screen)
does not buzz the phone. A session seen for the first time is not news, so restarting the server
says nothing. Queue sessions (`q<id>`) are left to the queue's own events, so a task never notifies
twice. Each notification has a tag (`session-<name>`, `queue`, `watcher`): the phone shows only the
newest per tag.

**How it is sent**: Web Push with the encryption written in `webpush.py` (RFC 8291 for the message,
RFC 8292 VAPID for the sender), using the `cryptography` package only for ECDH and AES-GCM. The
other choice was `pywebpush`, which does it in one call but adds `requests`, `py-vapid` and
`http_ece`; I chose fewer packages and code I can explain. The server's VAPID key is made once, at
`~/.local/share/ollagi/push/vapid.pem` (mode 600). Subscriptions live in
`~/.local/share/ollagi/push.db` (mode 600, one row per endpoint). Sending runs on its own thread, so
a slow push service never holds up the RAM watcher or the queue. Messages live 6 hours at the push
service (`TTL`) and are sent with `Urgency: high`.

**Safety**:
- Subscribing is a POST, so the `X-Ollagi` rule (0006) applies: another website cannot add a phone.
- The server only sends to known push services (Google's `fcm.googleapis.com` and
  `jmt17.google.com`, Mozilla, Apple, Microsoft), https on port 443, so a made-up subscription cannot
  make it send requests anywhere else, this laptop included.
- A subscription its push service has forgotten (answer 404 or 410) is deleted.

**On the page**: a Notifications card in System with Turn on / Turn off and Send a test. Permission
is only asked after a tap. Tapping a notification opens that session (or the queue) in the open
page, or opens the page.

## Consequences

- Chrome on Android delivers through Google's push service (FCM). The text is encrypted end to end
  to my phone, but Google sees when a message is sent and how big it is. The phone needs Google Play
  services, as for any Chrome notification.
- The question's text leaves the laptop (encrypted) in a "needs you" notification. If that is too
  much, the body could become just "needs you".
- One more dependency: `cryptography` (with `cffi` and `pycparser`).
- From a state change to the phone takes about 10 s (two reads 5 s apart) plus the push service's
  delivery time.
- Undo: Turn off on the phone, or delete `push.db`; without subscriptions nothing is sent. The
  `run_notifier` flag in `serve.py` turns the watching off.

## Checked

2026-10-21, on the laptop:
- 246 unit tests pass. The encryption matches RFC 8291's worked example byte for byte, and that test
  fails if one byte of the key derivation is wrong. The two-reads rule and the queue-session rule
  each fail their test when removed.
- Headless Chromium with a fresh profile, test server on port 8766 with the notifier on, through
  Google's real push service: Turn on subscribed and the server stored it; Send a test arrived and
  was shown ("ollagi / Notifications work on this phone."). A throwaway `bash` session drawing a
  pretend Claude screen: working then a question gave "pushtest needs you / Do you want to
  proceed?" (the service worker logged the decrypted message, and it was shown); working then
  finished gave "pushtest finished". Opening `/?session=pushtest` opened that session and the
  address went back to `/`. Turn off removed the subscription. No page errors.
- Headless Chromium has no notification tray and closes a notification after a few seconds; that
  is the test browser, not ollagi.
- Two bugs this found, both fixed before committing: Chromium without Google's API keys subscribes
  at `jmt17.google.com`, which the first allow-list refused; and after a refusal the card still
  said "On", because the browser kept its half of the subscription.

On my phone, 2026-10-21: the card first stayed at "…", because Chrome reused its saved copy of the
old app.js (the page's files had no Cache-Control). Fixed in 32b04f3: every page file is sent with
`no-cache` and an ETag, unchanged files answer 304, and app.js is loaded once as `app.js?v=2`. After
that, Turn on registered the phone (Google's `fcm.googleapis.com`) and the test notification arrived.

Not yet checked: a real "needs you" from a Claude session on the phone, a tap opening it, and the
watcher and queue notices in real use.

The full guide is `docs/guides/phone-app-and-notifications.md`.

## Sources

- RFC 8291, Message Encryption for Web Push: https://www.rfc-editor.org/rfc/rfc8291
- RFC 8188, the aes128gcm content coding: https://www.rfc-editor.org/rfc/rfc8188
- RFC 8292, VAPID: https://www.rfc-editor.org/rfc/rfc8292
- RFC 8030, the push protocol (TTL, Urgency): https://www.rfc-editor.org/rfc/rfc8030
- Push API: https://developer.mozilla.org/en-US/docs/Web/API/Push_API
- Notification options (tag, renotify): https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerRegistration/showNotification
