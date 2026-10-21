// ollagi's service worker: a small script the browser keeps running for this site, even when no
// page of it is open. Installing the page as an app needs one, and notifications (docs/decisions/0024)
// arrive here.
//
// It caches nothing on purpose: without the laptop the page has nothing to show, and a cached page
// would keep showing an old version after an update.

// A new version takes over at once, instead of waiting until every open page is closed.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
