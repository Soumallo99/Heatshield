/**
 * HeatShield service worker — offline-first PWA.
 *
 * WHAT THIS DOES
 *   - Precaches the app shell so it opens with no signal (heatwaves don't wait for 4G).
 *   - Network-first for /api/* so risk scores are fresh when online,
 *     falling back to the last cached response when offline.
 *   - Cache-first for static assets (hashed filenames from Vite).
 *   - Handles the push payload shape emitted by the Phase 5 alert service.
 *
 * REGISTER IT FROM THE APP (once, in main.tsx):
 *   if ('serviceWorker' in navigator)
 *     navigator.serviceWorker.register('/sw.js', { scope: '/' });
 *
 * NOTE: this file must be served from the site ROOT (not /assets/) or its scope
 * will be limited to a subdirectory and it will silently do nothing.
 * In Vite, put it in /public/sw.js.
 */

const VERSION = 'heatshield-v1';
const SHELL_CACHE = `${VERSION}-shell`;
const DATA_CACHE = `${VERSION}-data`;

const APP_SHELL = [
  '/',
  '/index.html',
  '/manifest.webmanifest',
  '/offline.html'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE)
      .then((cache) => cache.addAll(APP_SHELL).catch(() => {
        // Don't fail installation if a shell file is missing (e.g. offline.html
        // not authored yet) — the app still works online.
      }))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // ---- API: network first, fall back to last known data -------------------
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(DATA_CACHE).then((c) => c.put(request, copy));
          return response;
        })
        .catch(async () => {
          const cached = await caches.match(request);
          return cached ||
            new Response(
              JSON.stringify({ stale: true, error: 'offline', data: [] }),
              { headers: { 'Content-Type': 'application/json' } }
            );
        })
    );
    return;
  }

  // ---- Static assets: cache first ----------------------------------------
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        // revalidate in the background
        fetch(request).then((response) => {
          if (response.ok) {
            caches.open(SHELL_CACHE).then((c) => c.put(request, response.clone()));
          }
        }).catch(() => {});
        return cached;
      }
      return fetch(request)
        .then((response) => {
          if (response.ok && url.origin === self.location.origin) {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((c) => c.put(request, copy));
          }
          return response;
        })
        .catch(() => caches.match('/offline.html'));
    })
  );
});

/**
 * Phase 5 alert payload:
 *   { ward, risk, band, guidance, wbgt, timestamp }
 */
self.addEventListener('push', (event) => {
  let payload = {};
  try {
    payload = event.data ? event.data.json() : {};
  } catch {
    payload = { body: event.data ? event.data.text() : 'Heat alert' };
  }

  const title = payload.band === 'Critical'
    ? `CRITICAL HEAT RISK — ${payload.ward || 'Your ward'}`
    : `Heat alert — ${payload.ward || 'Your ward'}`;

  const options = {
    body: payload.guidance || payload.body || 'Check current heat risk.',
    icon: '/icons/icon-192.png',
    badge: '/icons/badge-72.png',
    tag: `heat-${payload.ward || 'all'}`,
    renotify: true,
    requireInteraction: payload.band === 'Critical',
    vibrate: [200, 100, 200],
    data: { url: payload.ward ? `/ward/${payload.ward}` : '/' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          if ('focus' in client) {
            client.navigate(target);
            return client.focus();
          }
        }
        return self.clients.openWindow(target);
      })
  );
});
