const CACHE_NAME = "catalogin-v2";

const URLS_TO_CACHE = [
  "/",
  "/search-page",
  "/auth-page",
  "/register-page",
  "/vip-page",
  "/terms-of-use",
  "/privacy-policy",
  "/static/style.css",
  "/static/common_layout.js",
  "/static/auth.js",
  "/static/app.js",
  "/manifest.webmanifest"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(URLS_TO_CACHE);
    })
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== CACHE_NAME)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        const responseClone = networkResponse.clone();

        caches.open(CACHE_NAME).then((cache) => {
          cache.put(event.request, responseClone);
        });

        return networkResponse;
      })
      .catch(() => caches.match(event.request))
  );
});