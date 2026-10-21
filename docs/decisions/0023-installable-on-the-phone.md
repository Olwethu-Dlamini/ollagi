# 0023: The page installs as an app on the phone

Date: 2026-10-21

Follows 0022 (HTTPS), which made the page a secure context, the first thing installing needs.

## Context

On the phone the page opened in a browser tab, with the address bar taking space and ollagi one tab
among many. Chrome on Android installs a page as an app (an icon on the home screen, full screen,
its own entry in the app switcher) when the page has a web app manifest and a service worker and is
served over https. Notifications (0024) need the service worker too.

## Decision

- `static/manifest.webmanifest`, served at `/manifest.webmanifest`: name, `start_url` and `scope`
  `/`, `display: standalone` (no browser bar), the page's dark colour, and icons at 192 and 512
  pixels, the 512 also marked `maskable`.
- The icons are the favicon's blue dot on the dark background, drawn by `scripts/make_icons.py`
  with the standard library (zlib and struct write the PNG). The dot stays inside the middle 80 %,
  so Android can cut the icon to a circle or a rounded square without losing any of it.
- `static/sw.js`, served at `/sw.js`: from the root, because a worker only covers the folder it is
  served from; with `Cache-Control: no-cache`, so the browser checks for a new version every time.
- The worker caches nothing. Without the laptop the page has nothing to show, and a cached page is a
  classic way to keep seeing an old version after an update. It takes over at once
  (`skipWaiting`, `clients.claim`).
- app.js registers the worker. Browsers allow that on https and on 127.0.0.1 only.

## Consequences

- The installed app is the same page at the same address: nothing to update separately, and the
  browser tab keeps working.
- The access rules (0006) apply unchanged: the manifest, the icons and the worker are plain GET
  requests through the same checks.
- Undo: delete the `<link rel="manifest">` line; the worker can stay or be removed with it.

## Checked

2026-10-21, headless Chromium at phone size, with a fresh profile, on a test server (port 8766, no
watcher, no queue): Chromium read the manifest with no errors, `Page.getInstallabilityErrors`
returned none, the worker was active and controlled the page, no page errors. (In an incognito
context Chromium answers `in-incognito`, which is about the test browser, not the page.)

On my phone, 2026-10-21: installed from Chrome and opened from its icon.

## Sources

- Web app manifest: https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Manifest
- What Chrome needs before it offers to install: https://web.dev/articles/install-criteria
- Maskable icons and their safe zone: https://web.dev/articles/maskable-icon
- Service worker scope: https://developer.mozilla.org/en-US/docs/Web/API/ServiceWorkerContainer/register
