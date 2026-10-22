# Guide: ollagi as a phone app, with notifications

This guide explains the whole feature in one place: what it does, how to set it up, how every piece
works, how it was tested, what can go wrong, and answers to the questions people ask about it. The
short records of each choice are in `docs/decisions/0022` (HTTPS), `0023` (the app), `0024`
(notifications) and `0028` (the sound); the ideas behind them (service workers, ECDH, HKDF, AES-GCM, VAPID) are explained
in `docs/learning/README.md`.

## 1. What it does

- **The page installs as an app.** On an Android phone, Chrome's "Install app" puts an ollagi icon
  on the home screen. It opens full screen, without the browser bar, and has its own place in the
  app switcher. It is still the same web page at the same address: there is no app store app and
  nothing to update separately.
- **The phone gets notifications**, even when ollagi is closed:

  | When | Notification | Tapping it opens |
  |------|--------------|------------------|
  | A session shows a question, a permission request or a plan to approve | "api needs you", with the question as the text | that session |
  | A session finishes its turn after working | "api finished" | that session |
  | A queue task is done, waits for me, fails, cannot start, or hits a usage limit | "Queue", with what happened | the Queue tab |
  | The RAM watcher pauses, stops or resumes a session | "Memory low", with what it did | that session |

  Each session keeps at most one notification on the phone: a new one replaces the old one and
  buzzes again. A "needs you" stays on the screen until it is tapped or dismissed; the others clear
  on their own. A yes-or-no question (a permission, the trust prompt) has **Allow** and **Deny**
  buttons on the notification: a tap answers it without opening the app, and only if the same
  question is still on the screen (decision 0029); otherwise a new notification says so. Every notification asks the phone to vibrate, and while the page is in front it
  plays a short chime of its own (decision 0028). The notification's sound is the phone's setting.

- **It costs no Claude tokens.** Nothing here calls Claude. The server only reads the screens tmux
  already has, the same way the page does.

## 2. Setting it up on a phone

Needs: the Tailscale app on the phone, signed in to the same account, and the laptop's ollagi page
on https (decision 0022).

1. Open the https address in Chrome (scan the QR code on the laptop's System tab, or `ollagi qr`).
2. Chrome menu (⋮) → **Install app** (on some phones: **Add to home screen** → Install).
3. Open ollagi from the new icon.
4. **System** tab → **Notifications** card → **Turn on**, and allow notifications when Chrome asks.
5. **Send a test**. "ollagi: Notifications work on this phone." should arrive within seconds.

To stop: **Turn off** in the same card. That deletes the phone's subscription on the server and in
the browser. Turning notifications off in Android's settings for the app works too.

Several devices can be on at once; each gets every notification. The card says how many are on.

## 3. How it works, end to end

### 3.1 The pieces

| Piece | File | Job |
|-------|------|-----|
| Manifest | `src/ollagi/static/manifest.webmanifest` | Name, icons, colours, full-screen display: what Chrome needs to install the page |
| Icons | `static/icon-192.png`, `icon-512.png`, drawn by `scripts/make_icons.py` | The home-screen icon (a blue dot on the dark background) |
| Service worker | `src/ollagi/static/sw.js`, served at `/sw.js` | Lives in the browser; receives push messages, shows them, handles taps |
| Page code | `src/ollagi/static/app.js` (Notifications section) | The card: asks permission, subscribes, sends the subscription to the server, follows links |
| Encryption and sending | `src/ollagi/webpush.py` | Encrypts a message to the phone's keys (RFC 8291), signs the request (VAPID, RFC 8292), POSTs it |
| Deciding and keeping | `src/ollagi/notify.py` | Which changes are worth a notification; the list of phones (SQLite); the sending thread |
| Server wiring | `src/ollagi/web.py` | The `/api/push` routes; hands queue events and watcher actions to the notifier; starts its threads |
| Data on the laptop | `~/.local/share/ollagi/push.db`, `~/.local/share/ollagi/push/vapid.pem` | The phones, and the server's own key. Both readable by my user only |

### 3.2 Turning it on (once per device)

```
phone (page)                         laptop (ollagi server)              Google's push service
    | GET /api/push  ------------------> public key of the server
    | Notification.requestPermission()  (Chrome asks me: Allow?)
    | pushManager.subscribe(key) ------------------------------------------> registers this phone
    | <---------------------------------------------------------------------- endpoint + p256dh + auth
    | POST /api/push/subscribe --------> checks it, stores it in push.db
```

- The **endpoint** is an https address at Google's push service that stands for this phone's
  browser. **p256dh** is a public key made by the phone, and **auth** a 16-byte secret made by the
  phone. Only the phone has the private key that goes with p256dh.
- The page subscribes with the server's **public key**. From then on Google only accepts messages
  for this endpoint when they are signed with the matching private key, which never leaves the laptop.

### 3.3 A notification

```
session screen --(every 5 s)--> state "needs_you" twice in a row --> notice "api needs you"
notice --> sending thread --> encrypt to the phone's keys --> sign (VAPID) --> POST to the endpoint
Google's push service --> wakes Chrome on the phone --> Chrome decrypts --> sw.js shows it
tap --> sw.js brings ollagi forward (or opens it) at /?session=api --> the page opens that session
```

In more detail:

1. **Watching.** A thread in the server reads every session's state every 5 seconds
   (`claude_screen.read`, the same reading the page's state dots use).
2. **Deciding** (`notify.SessionWatch`):
   - a state counts only once it has been read **twice in a row**. Between two tool calls Claude's
     spinner can vanish for a moment while an older "✻ Worked for 3s" line is still on the screen,
     so a single read can say "done" when Claude is still working;
   - a session seen for the first time is not news, so restarting the server sends nothing;
   - queue sessions (named `q1`, `q2`, ...) are skipped here, because the queue sends its own,
     more useful notices about its tasks.
   Queue events and RAM watcher actions are turned into notices where they happen.
3. **Sending** happens on its own thread, so a slow network never holds up the RAM watcher or the
   queue. For each phone in `push.db`:
   - **encrypt** (`webpush.encrypt`): a fresh key pair for this one message; ECDH with the phone's
     public key gives a shared secret; HKDF mixes it with the phone's auth secret and a random
     salt into an AES key and a nonce; AES-128-GCM encrypts the JSON message
     `{title, body, tag, url, urgent}`;
   - **sign** (`webpush.vapid_authorization`): a JSON Web Token naming Google's push service and an
     expiry 12 hours ahead, signed with the server's key;
   - **POST** to the endpoint with `TTL: 21600` (Google keeps it up to 6 hours if the phone is off;
     an older "needs you" is stale) and `Urgency: high` (deliver now, even in battery saving).
4. **Answers**: 201 means accepted. 404 or 410 means Google no longer knows this phone (the app
   was uninstalled, or the subscription expired), so it is deleted from `push.db`. Anything else
   is recorded in the card's event list.
5. **On the phone**, Chrome decrypts the message and hands it to `sw.js`, which shows it with the
   ollagi icon. The `tag` (`session-api`, `queue`, `watcher`) makes a new notification replace the
   last one with the same tag. `urgent` (a "needs you") keeps it on screen until it is dealt with
   and vibrates longer. `sw.js` then tells every open page, and a page in front plays its chime.
6. **A tap**: `sw.js` brings the open ollagi forward and tells it which address to show, or opens
   ollagi at that address. `app.js` reads `?session=NAME` or `?view=queue`, opens it, and puts the
   address back to `/`.

From a state change to the phone takes about 10 seconds (two reads 5 seconds apart) plus Google's
delivery, usually a second or two.

### 3.4 The API

| Route | Does |
|-------|------|
| `GET /api/push` | The server's public key, how many devices are on, the last sends |
| `POST /api/push/subscribe` | Store a device `{"endpoint", "keys": {"p256dh", "auth"}}` |
| `POST /api/push/unsubscribe` | Forget a device `{"endpoint"}` |
| `POST /api/push/test` | Send a test to every device (409 when none is on) |
| `POST /api/sessions/NAME/answer` | A notification button: `{"key", "question"}`; presses the key only if that question is still on screen, else 409 |
| `GET /manifest.webmanifest`, `GET /sw.js` | The manifest and the service worker |

## 4. Security and privacy

- **Who can turn notifications on.** The same rules as the rest of the page (decision 0006):
  only my Tailscale login reaches it, and every POST needs the `X-Ollagi: 1` header, which another
  website cannot make my browser send. So no other site can add a device.
- **Where the server sends.** Only to known push services, over https on port 443:
  `fcm.googleapis.com` and `jmt17.google.com` (Google), `push.services.mozilla.com` (Firefox),
  `push.apple.com` (Safari), `notify.windows.com` (Edge on Windows). A made-up subscription
  cannot make the server send requests to any other address, this laptop included.
- **Who can read a notification.** Only the phone. Google carries an encrypted message: it sees
  that one was sent, when, and roughly how big it is, but not the text.
- **What leaves the laptop.** The notice text, encrypted: a session name, and for "needs you" the
  question Claude asked (cut to 500 characters). Nothing else from the screen.
- **The keys on the laptop.** `vapid.pem` (the server's private key) and `push.db` (each phone's
  endpoint and secret) are mode 600: readable by my user only. If `vapid.pem` were deleted, a new
  key would be made and every device would have to turn notifications on again.
- **The repo is public**, so no endpoint, key, tailnet name or email is ever committed.

## 5. How it was tested

- **247 unit tests** (`uv run pytest`), including:
  - the encryption reproduces the worked example in RFC 8291 byte for byte. This is the strongest
    test: encrypting and decrypting with my own code would pass even if both halves had the same
    mistake, but a published example cannot be matched by accident. Changing one byte of the key
    derivation makes it fail;
  - the VAPID token's header, claims and signature are checked with the public key;
  - the two-reads rule and the queue-session rule each fail their test when removed;
  - only known push services are accepted; refused subscriptions are not stored;
  - a forgotten phone (410) is deleted, a network failure keeps it and is reported;
  - the page's files are sent with `no-cache` and answer 304 when unchanged.
- **Through Google's real push service**, with headless Chromium on the laptop and a throwaway
  `bash` session drawing a pretend Claude screen: Turn on, Send a test, "pushtest needs you" with
  the question, "pushtest finished", and opening `/?session=pushtest` all worked. Turn off removed
  the device again.
- **On my phone**, 2026-10-21: installed, Turn on registered it (Google's `fcm.googleapis.com`),
  and the test notification arrived.

## 6. Troubleshooting

| What I see | Why | What to do |
|------------|-----|------------|
| The Notifications card shows only "…" | The phone is running an old copy of the page's code | Close ollagi fully (swipe it away) and open it again. Since `32b04f3` the server makes browsers check for new versions, so this should not come back |
| "Needs the https address" | The page was opened on `http://` | Use the https address (scan the QR code again) |
| "Blocked in this browser's site settings" | Notifications were denied once; Chrome will not ask again | Android settings → Apps → ollagi (or Chrome) → Notifications → allow; or Chrome → site settings for the address |
| "This browser cannot show them" | The browser has no Push API | Use Chrome on Android |
| Turn on gives an error | The server refused the subscription (the message says why); the browser's half is undone | Read the message; the card's event list has more |
| Send a test says "Not sent: ..." | Google refused or the laptop has no internet | The reason is in the message and in the event list |
| No notification while a session clearly waits | The laptop is asleep or offline, or the session's screen is not recognised as a question (state detection knows numbered menus only) | Check the session's state dot on the page; see `docs/suggestions.md` about the lid |
| Notifications stopped after reinstalling the app | The old subscription is gone (Google answered 410 and the server deleted it) | Turn on again |
| A notification arrives but makes no sound | A page cannot choose a sound; Android plays the one set for the app's notification channel, and on many phones a new channel starts silent or "quiet" | Android Settings → Apps → ollagi (or Chrome → Sites) → Notifications → set the channel to make sound. The page vibrates the phone and, while it is in front, plays a chime of its own (decision 0028) |

**The "…" bug, as it happened.** Until `32b04f3`, the server sent the page's files without a
`Cache-Control` header. Browsers then guess how long a copy stays good, and Chrome reused its saved
`app.js` from before the update while fetching the new page around it. So the new Notifications card
appeared, but the code that fills it in was not there, and it stayed at its "…" placeholder. The fix:
every page file is sent with `Cache-Control: no-cache` (the browser asks each time whether its copy is
current) and an `ETag` naming the version, and the server answers `304 Not Modified` when nothing
changed, so the check costs almost nothing. The page loads `app.js?v=2` once, so phones holding the
old copy were forced to fetch the new one.

## 7. Questions people ask

**Why not a real Android app?** It would need its own code, a build, signing and an install path,
and every change twice. The installed web app is the same page I already have, gets updates by
reloading, and Chrome provides the icon, the full screen and the notifications.

**Why do notifications go through Google?** On Android, Chrome can only be woken through Google's
push service (Firebase Cloud Messaging, FCM); that is how every Chrome notification works. The message
is encrypted for the phone, so Google cannot read it.

**Why write the encryption yourself instead of using a library?** The project is for learning, and
the choice was made on 2026-10-21: `cryptography` alone, with the protocol (about 80 lines) written
out, versus `pywebpush`, which adds `requests`, `py-vapid` and `http_ece`. The risky parts, the
elliptic-curve maths and AES-GCM, still come from `cryptography`; only the way they are combined is
mine, and that is checked against the RFC's published example.

**How do you know the encryption is right?** The RFC 8291 test: fixed keys and salt from the RFC
must give exactly the RFC's encrypted message, and they do. Then Google's real push service
accepted the messages and real Chrome decrypted and showed them.

**Does this use Claude tokens?** No. Notifications come from reading tmux screens and sending
HTTPS requests. Only the Summary button (decision 0019) uses Claude.

**What if the laptop is asleep?** Then nothing is watched and nothing is sent. Messages already sent
wait at Google up to 6 hours for the phone. Keeping the laptop awake with the lid closed is an open
suggestion in `docs/suggestions.md`.

**Can it spam me?** At most one notification per session at a time on the phone (the tag replaces
it), only on a change of state that held for two reads, never for sessions already in a state when
the server started, and queue sessions are announced once by the queue, not twice.

**Why a 6-hour TTL?** A notification that a session needs me is useful soon or not at all; if the
phone was off all night, a pile of stale ones is worse than none.

**Why does the service worker not cache anything?** Without the laptop the page has nothing to show,
and a cached page is a common way to keep seeing an old version after an update. The "…" bug was
exactly that kind of problem, caused by the browser's own cache.

**Where is the data, and how do I reset everything?** `~/.local/share/ollagi/push.db` (devices) and
`~/.local/share/ollagi/push/vapid.pem` (server key). Deleting `push.db` forgets every device;
deleting both and restarting the service makes a new key, and every device turns on again.

**How do I turn the watching off completely?** Turn off on every device (with no devices nothing
is sent), or start the server with `run_notifier=False` in `serve.py`.

## 8. Commits

| Commit | What |
|--------|------|
| `406eaa7` | Draw the app icons with a small stdlib script |
| `7c30330` | Let the phone install the page as an app (manifest, service worker) |
| `701ee57` | Decision 0023 |
| `eb36ede` | Encrypt and sign push messages ourselves (RFC 8291, RFC 8292) |
| `29150a9` | Decide what is worth a notification, and keep the phones to send it to |
| `f583f6d` | Send notifications from the server (routes, threads, queue and watcher hooks) |
| `d6ffa42` | Turn notifications on from the page, and open what a notification is about |
| `dbe7ea0` | Decision 0024 and the learning notes |
| `32b04f3` | Make browsers check for a new version of the page's files (the "…" fix) |
