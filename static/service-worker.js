const APP_VERSION = self.APP_VERSION || "local-dev";
const STATIC_CACHE = `catalogin-static-${APP_VERSION}`;

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    Promise.all([
      caches.keys().then((cacheNames) =>
        Promise.all(
          cacheNames.map((cacheName) => {
            if (cacheName !== STATIC_CACHE) {
              return caches.delete(cacheName);
            }

            return Promise.resolve();
          })
        )
      ),

      self.clients.claim()
    ])
  );
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
   * Páginas HTML sempre vêm do servidor.
   */
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request, {
        cache: "no-store"
      })
    );

    return;
  }

  /*
   * APIs e rotas dinâmicas nunca usam cache.
   */
  const dynamicRoutes = [
    "/ads/",
    "/anuncios/",
    "/search",
    "/locations/",
    "/reports",
    "/auth/",
    "/public/",
    "/me",
    "/my-ads/",
    "/vitrine-ads",
    "/feed",
    "/plans-config",
    "/vip/"
  ];

  const isDynamicRoute = dynamicRoutes.some((route) =>
    url.pathname.startsWith(route)
  );

  if (isDynamicRoute) {
    event.respondWith(
      fetch(request, {
        cache: "no-store"
      })
    );

    return;
  }

  /*
   * Arquivos estáticos:
   * tenta a rede primeiro.
   * O cache serve apenas se não houver conexão.
   */
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.open(STATIC_CACHE).then(async (cache) => {
        try {
          const networkResponse = await fetch(request, {
            cache: "no-store"
          });

          if (networkResponse && networkResponse.ok) {
            await cache.put(
              request,
              networkResponse.clone()
            );
          }

          return networkResponse;
        } catch (error) {
          const cachedResponse = await cache.match(request);

          if (cachedResponse) {
            return cachedResponse;
          }

          throw error;
        }
      })
    );
  }
});