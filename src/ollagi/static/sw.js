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
// and hands it here as JSON: {title, body, tag, url, urgent, actions}. A tag keeps one notification per
// session: a new one replaces the old, and renotify makes the phone buzz again for it. An urgent
// one (a question waiting for me) stays on screen until it is tapped or dismissed.
// The sound itself is the phone's: a page cannot choose one, only ask to vibrate (Android does;
// other browsers ignore it). Android decides from the app's notification settings.
self.addEventListener("push", (event) => {
  const message = event.data ? event.data.json() : { title: "ollagi", body: "", tag: "ollagi", url: "/" };
  event.waitUntil((async () => {
    await self.registration.showNotification(message.title, {
      body: message.body,
      tag: message.tag,
      renotify: true,
      requireInteraction: Boolean(message.urgent),
      vibrate: message.urgent ? [200, 100, 200, 100, 200] : [200, 100, 200],
      icon: "/static/icon-192.png",
      // Allow and Deny on a yes-or-no question (docs/decisions/0029): each is the number key to press.
      actions: (message.actions || []).map(([key, title]) => ({ action: key, title })),
      data: { url: message.url || "/", question: message.body },
    });
    // An open page plays a chime of its own (app.js), since the phone's sound may be off.
    for (const page of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) {
      page.postMessage({ type: "notice", urgent: Boolean(message.urgent) });
    }
  })());
});

// Tapping a notification: bring the open page forward and tell it what to show, or open a new one.
// Tapping one of its buttons: answer the question from here, without opening the page.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";
  if (event.action) {
    event.waitUntil(answer(url, event.action, event.notification.data?.question || ""));
    return;
  }
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

// Press the chosen key in the session, only if it is still asking the same question (the server
// checks). If it is not, say so in a new notification that opens the session.
async function answer(url, key, question) {
  const session = new URL(url, self.location.origin).searchParams.get("session");
  let problem = null;
  try {
    const response = await fetch(`/api/sessions/${session}/answer`, {
      method: "POST", headers: { "Content-Type": "application/json", "X-Ollagi": "1" },
      body: JSON.stringify({ key, question }),
    });
    if (!response.ok) problem = (await response.json().catch(() => ({}))).detail || response.statusText;
  } catch (error) {
    problem = "the laptop could not be reached";
  }
  if (problem) {
    await self.registration.showNotification(`${session}: not answered`, {
      body: problem, tag: `session-${session}`, icon: "/static/icon-192.png", data: { url },
    });
  }
}

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
