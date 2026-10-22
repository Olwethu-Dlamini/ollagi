// ollagi's service worker: a small script the browser keeps running for this site, even when no
// page of it is open. Installing the page as an app needs one, and notifications (docs/decisions/0024)
// arrive here.
//
// It caches nothing on purpose: without the laptop the page has nothing to show, and a cached page
// would keep showing an old version after an update.

// A new version takes over at once, instead of waiting until every open page is closed.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// ---- notifications (docs/decisions/0024) --------------------------------------------------------
// The server encrypts each message to this browser (src/ollagi/webpush.py); the browser decrypts it
// and hands it here as JSON: {title, body, tag, url, urgent}. A tag keeps one notification per
// session: a new one replaces the old, and renotify makes the phone buzz again for it. An urgent
// one (a question waiting for me) stays on screen until it is tapped or dismissed.
// The sound itself is the phone's: a page cannot choose one, only ask to vibrate (Android does;
// other browsers ignore it). Android decides from the app's notification settings.
self.addEventListener("push", (event) => {
  const message = event.data ? event.data.json() : { title: "ollagi", body: "", tag: "ollagi", url: "/" };
  event.waitUntil(self.registration.showNotification(message.title, {
    body: message.body,
    tag: message.tag,
    renotify: true,
    requireInteraction: Boolean(message.urgent),
    vibrate: message.urgent ? [200, 100, 200, 100, 200] : [200, 100, 200],
    icon: "/static/icon-192.png",
    data: { url: message.url || "/" },
  }));
});

// Tapping a notification: bring the open page forward and tell it what to show, or open a new one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  event.waitUntil((async () => {
    const [page] = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    if (page) {
      await page.focus();
      page.postMessage({ type: "open", url });
    } else {
      await self.clients.openWindow(url);
    }
  })());
});

// The browser may replace a subscription by itself; then it gives the server the new one.
self.addEventListener("pushsubscriptionchange", (event) => {
  event.waitUntil((async () => {
    const { public_key: key } = await (await fetch("/api/push")).json();
    const sub = await self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: fromBase64Url(key) });
    await fetch("/api/push/subscribe", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Ollagi": "1" }, body: JSON.stringify(sub),
    });
  })());
});

function fromBase64Url(text) {
  const plain = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(plain, (c) => c.charCodeAt(0));
}
