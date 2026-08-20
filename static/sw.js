// Minimal service worker: caches the app shell so the icons/CSS/JS load
// instantly on repeat visits and the app still opens (even if a page
// request fails) when connectivity is flaky. This is NOT full offline
// transaction support - that's future work (see README) because it
// needs conflict resolution and sync logic, not just caching.
const CACHE_NAME = "sme-os-shell-v1";
const SHELL_ASSETS = [
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  // Cache-first for static assets only; everything else (pages, HTMX
  // partials, form posts) always goes to the network so data stays fresh.
  if (event.request.url.includes("/static/")) {
    event.respondWith(
      caches.match(event.request).then((cached) => cached || fetch(event.request))
    );
  }
});
