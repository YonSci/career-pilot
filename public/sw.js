/* Jobs Find AI service worker: installable app shell and push notifications.
   Only static assets under /app/ are cached; API calls always go to the network. */
const VERSION = "jfa-v1";
const SHELL = ["/app/", "/app/manifest.webmanifest", "/app/icons/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (url.pathname.startsWith("/app/assets/") || url.pathname.startsWith("/app/icons/")) {
    // Hashed assets: cache first.
    event.respondWith(caches.match(event.request).then((hit) => hit || fetch(event.request).then((res) => { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(event.request, copy)); return res; })));
    return;
  }
  if (event.request.mode === "navigate" && url.pathname.startsWith("/app")) {
    // App shell: network first, cached shell when offline.
    event.respondWith(fetch(event.request).then((res) => { const copy = res.clone(); caches.open(VERSION).then((c) => c.put("/app/", copy)); return res; }).catch(() => caches.match("/app/")));
  }
});

self.addEventListener("push", (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: "Jobs Find AI", body: event.data ? event.data.text() : "" }; }
  const title = data.title || "Jobs Find AI";
  const options = {
    body: data.body || "",
    icon: "/app/icons/icon-192.png",
    badge: "/app/icons/icon-192.png",
    tag: data.tag || "jfa",
    renotify: !!data.tag,
    data: { url: data.url || "/app/" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/app/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      const open = list.find((c) => c.url.includes("/app"));
      if (open) { open.navigate(target); return open.focus(); }
      return self.clients.openWindow(target);
    })
  );
});
