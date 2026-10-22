# 0028: The notification sound

Date: 2026-10-22

Follows 0024 (notifications on the phone).

## Context

Notifications arrived on the phone without a sound. A web page cannot choose a notification's
sound: the `sound` option of the Notifications API was never implemented, and on Android the sound
comes from the notification channel the phone creates for the app, which on many phones starts
silent or "quiet". What a page can do: ask the phone to vibrate, keep a notification on screen,
and make a sound itself while it is open.

## Decision

- A `Notice` has an `urgent` flag, set for "needs you" only. The service worker shows an urgent
  notification with `requireInteraction` (it stays until tapped or dismissed) and a longer
  vibration; every notification asks to vibrate (`[200, 100, 200]`). Android honours `vibrate`,
  other browsers ignore it.
- After showing a notification the service worker tells every open page, and a page in front
  plays a short chime of its own: two rising tones, three for a question (Web Audio, in app.js).
  Browsers only let a page make sound after a tap, so the sound system is opened on the first tap
  or key and kept. In the background nothing plays: the notification itself is the signal there.
- The Notifications card says where the phone's setting is (Android: Settings → Apps → ollagi →
  Notifications), and the guide's troubleshooting table has the row.

Considered and not chosen: a toggle for the chime. It only plays on a device that receives the
push, in front, and Turn off silences everything; a toggle can come if it annoys.

## Consequences

- A question keeps its notification on the phone's screen until it is dealt with; "finished",
  queue and watcher notices still clear on their own.
- Whether the phone itself makes a sound is still the phone's setting. The card says so.
- Undo: drop `urgent` from `Notice` (the service worker treats a missing flag as false); remove
  the `notice` message and `chime` from sw.js and app.js.

## Checked

2026-10-22, on the laptop: 255 unit tests (a "needs you" notice is urgent, others are not; the
message sent to a phone carries the flag). Headless Chromium: after a tap, a service-worker
message for an urgent notice created three oscillators (the real AudioContext, wrapped to count).

On my phone, 2026-10-22: the notifications arrived silent, without vibration, only the light.
That was the phone's notification category for ollagi, set to silent; once it was switched to
alerting, a test notification sounded. Nothing in the code changed for that. An ntfy server on the
laptop had been considered as a way round it and was not needed.

## Sources

- Notification options: https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerRegistration/showNotification
- Autoplay and user activation: https://developer.chrome.com/blog/autoplay
