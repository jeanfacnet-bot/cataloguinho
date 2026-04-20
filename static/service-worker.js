const CACHE_NAME = "catalogin-v1";
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
    )
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  // 🔴 NUNCA interceptar métodos não GET
  if (request.method !== "GET") {
    return;
  }

  // 🔴 NÃO interceptar APIs do backend
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