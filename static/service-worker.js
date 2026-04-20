const CACHE_NAME = "catalogin-v2";
const URLS_TO_CACHE = [
  "/",
  "/search-page",
  "/auth-page",
  "/register-page",
  "/vip-page",
  "/static/style.css",
  "/static/common_layout.js",
  "/static/auth.js"
];

self.addEventListener("install", (event) => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(URLS_TO_CACHE))
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
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET") {
    return;
  }

  if (
    url.pathname.startsWith("/ads") ||
    url.pathname.startsWith("/auth") ||
    url.pathname.startsWith("/my-ads") ||
    url.pathname.startsWith("/users") ||
    url.pathname.startsWith("/vip") ||
    url.pathname.startsWith("/reports") ||
    url.pathname.startsWith("/locations") ||
    url.pathname.startsWith("/public")
  ) {
    return;
  }

  event.respondWith(
    caches.match(request).then((cachedResponse) => {
      return cachedResponse || fetch(request);
    })
  );
});