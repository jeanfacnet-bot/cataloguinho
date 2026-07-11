const APP_VERSION = self.APP_VERSION || "fallback";
const STATIC_CACHE = `catalogin-static-${APP_VERSION}`;

const STATIC_ASSETS = [
  "/static/style.css",
  "/static/common_layout.js",
  "/static/auth.js",
  "/static/app.js"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(async (cache) => {
      await Promise.allSettled(
        STATIC_ASSETS.map((url) =>
          cache.add(`${url}?v=${encodeURIComponent(APP_VERSION)}`)
        )
      );
    })
  );

  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(
        cacheNames
          .filter((cacheName) => cacheName !== STATIC_CACHE)
          .map((cacheName) => caches.delete(cacheName))
      )
    )
  );

  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    return;
  }

  /*
   * Páginas HTML:
   * sempre procura primeiro no servidor.
   * Nunca mantém uma página dinâmica antiga como resposta principal.
   */
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request, {
        cache: "no-store"
      }).catch(() => caches.match("/"))
    );

    return;
  }

  /*
   * APIs e páginas dinâmicas:
   * nunca passam pelo cache do service worker.
   */
  if (
    url.pathname.startsWith("/ads/") ||
    url.pathname.startsWith("/anuncios/") ||
    url.pathname.startsWith("/search") ||
    url.pathname.startsWith("/locations/") ||
    url.pathname.startsWith("/auth/") ||
    url.pathname.startsWith("/reports") ||
    url.pathname.startsWith("/public/")
  ) {
    event.respondWith(
      fetch(request, {
        cache: "no-store"
      })
    );

    return;
  }

  /*
   * Arquivos estáticos:
   * mostra rapidamente o cache, mas atualiza em segundo plano.
   */
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(async (cache) => {
        const cachedResponse = await cache.match(request);

        const networkResponsePromise = fetch(request).then(
          (networkResponse) => {
            if (networkResponse && networkResponse.ok) {
              cache.put(request, networkResponse.clone());
            }

            return networkResponse;
          }
        );

        return cachedResponse || networkResponsePromise;
      })
    );
  }
});