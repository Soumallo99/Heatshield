/*
 * HeatShield service worker — app shell plus last-known phone data.
 *
 * All scope-relative paths are intentional. The production app may live at
 * https://owner.github.io/Heatshield/, where an absolute /sw.js or /api path
 * escapes the repository subdirectory and silently breaks installation.
 */
/*
 * CACHE-BUMP DISCIPLINE — read this before touching anything below.
 *
 * The shell strategy is cache-first, which is what makes a cold open on a
 * phone instant and offline-proof. The cost: an already-installed app keeps
 * serving the OLD build forever, because index.html and the hashed assets it
 * points at are answered from the cache without ever asking the network.
 *
 * So: EVERY release that changes shipped frontend code bumps VERSION below
 * (…-v2 -> …-v3). The bump renames every cache, and the activate handler
 * deletes the caches that do not start with the new VERSION — that is the
 * whole migration mechanism. If you forget, users stay on the old build until
 * they clear site data by hand; if you skip it "just this once", the version
 * number stops meaning anything.
 */
const VERSION = 'heatshield-phone-v4'
const SHELL_CACHE = `${VERSION}-shell`
const DATA_CACHE = `${VERSION}-data`
const TILE_CACHE = `${VERSION}-tiles`
const TILE_LIMIT = 600

const SCOPE_URL = new URL(self.registration.scope)
const SCOPE_PATH = SCOPE_URL.pathname.replace(/\/$/, '')
const scopedURL = (path) => new URL(path.replace(/^\//, ''), self.registration.scope).toString()
const inScope = (path) => `${SCOPE_PATH}/${path.replace(/^\//, '')}`.replace(/\/+/g, '/')

const APP_SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './offline.html',
]
const OFFLINE_PAGE = scopedURL('offline.html')
const GEOJSON = scopedURL('data/kolkata_wards.geojson')
/* Tile hosts get their own bounded cache. Keep this list to providers the
 * shipped basemap registry (src/basemaps.js) may actually request — CARTO was
 * removed from both places after ~2026-08-28, when its keyless raster
 * endpoints started answering HTTP 200 with an "API KEY REQUIRED" watermark.
 * tile.openstreetmap.org is here because it is the registry's OSM_FALLBACK. */
const TILE_HOSTS = [
  'server.arcgisonline.com',
  'tile.opentopomap.org',
  'tile.openstreetmap.org',
]

async function trimTileCache() {
  const cache = await caches.open(TILE_CACHE)
  const keys = await cache.keys()
  if (keys.length > TILE_LIMIT) {
    await Promise.all(keys.slice(0, keys.length - TILE_LIMIT).map((key) => cache.delete(key)))
  }
}

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(SHELL_CACHE)
    // Cache shell entries independently: a missing optional asset must not
    // make the entire worker redundant.
    await Promise.all(APP_SHELL.map((path) => cache.add(path).catch(() => undefined)))
    await cache.add(GEOJSON).catch(() => undefined)
    await self.skipWaiting()
  })())
})

self.addEventListener('message', (event) => {
  if (event.data?.type === 'SKIP_WAITING') self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => !key.startsWith(VERSION)).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return
  const url = new URL(request.url)

  // A dev API is relative to this app scope (/api locally, /Heatshield/api on
  // a static host). Network first; the last successful response remains useful
  // while a phone has no signal.
  if (url.pathname.startsWith(inScope('api/'))) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) caches.open(DATA_CACHE).then((cache) => cache.put(request, response.clone()))
          return response
        })
        .catch(async () => {
          const cached = await caches.match(request)
          return cached || new Response(JSON.stringify({ stale: true, error: 'offline', data: [] }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
        })
    )
    return
  }

  // Basemap tiles have their own finite cache: tile panning must not evict the
  // small app shell or the compact static citizen snapshot.
  if (TILE_HOSTS.some((host) => url.hostname.endsWith(host))) {
    event.respondWith((async () => {
      const cache = await caches.open(TILE_CACHE)
      const cached = await cache.match(request)
      const network = fetch(request)
        .then((response) => {
          if (response.ok || response.type === 'opaque') {
            cache.put(request, response.clone()).then(trimTileCache)
          }
          return response
        })
        .catch(() => cached || new Response('', { status: 504 }))
      return cached || network
    })())
    return
  }

  // Hash routes do not need server rewrites, but a navigation with an unusual
  // static-host path still gets index.html when the network is unavailable.
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        fetch(request)
          .then((response) => {
            if (response.ok && url.origin === self.location.origin) {
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, response.clone()))
            }
          })
          .catch(() => undefined)
        return cached
      }
      return fetch(request)
        .then((response) => {
          if (response.ok && url.origin === self.location.origin) {
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, response.clone()))
          }
          return response
        })
        .catch(() => request.mode === 'navigate'
          ? caches.match(scopedURL('index.html')).then((page) => page || caches.match(OFFLINE_PAGE))
          : caches.match(OFFLINE_PAGE))
    })
  )
})

self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { body: event.data ? event.data.text() : 'Heat alert' }
  }
  const title = payload.band === 'Critical'
    ? `CRITICAL HEAT RISK — ${payload.ward || 'Your area'}`
    : `Heat alert — ${payload.ward || 'Your area'}`
  const options = {
    body: payload.guidance || payload.body || 'Open HeatShield for the latest brief.',
    icon: scopedURL('icons/icon-192.png'),
    badge: scopedURL('icons/badge-72.png'),
    tag: `heat-${payload.ward || 'all'}`,
    renotify: true,
    requireInteraction: payload.band === 'Critical',
    vibrate: [200, 100, 200],
    data: { url: scopedURL('#/phone') },
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL(event.notification.data?.url || scopedURL('#/phone'), self.registration.scope).href
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
    for (const client of clients) {
      if ('focus' in client) {
        client.navigate(target)
        return client.focus()
      }
    }
    return self.clients.openWindow(target)
  }))
})
