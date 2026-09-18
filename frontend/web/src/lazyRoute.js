/**
 * Route chunks: preloaded at the moment of intent, retried, and self-healing.
 *
 * WHY THIS MODULE EXISTS
 *
 * The app is split per route, so a route's code is fetched the first time you
 * visit it — the Citizen tab being the one people press most often. The bug this
 * fixes was reported as "when I press the Citizen tab I have to reload the page
 * before it opens", and there were two independent causes:
 *
 *  1. **Nothing was requested until the animation finished.** The router wrapped
 *     the pages in `AnimatePresence mode="wait"`, which by definition does not
 *     mount the incoming page until the outgoing one has finished animating out
 *     (~0.5 s), and the incoming chunk is only requested when the incoming page
 *     renders. So pressing a tab spent half a second downloading nothing, then
 *     started the fetch. That is now an enter-only transition (App.jsx) and the
 *     fetch starts on the press itself, via `loadChunk` being called from the
 *     nav handler before the hash changes.
 *  2. **A failed chunk fetch was a dead end.** Every route's code lives in a
 *     hashed file. After a deploy the hashes change; a browser (or a service
 *     worker) still holding the previous release's `index.html` asks for a file
 *     that no longer exists, `import()` rejects, and the tab never opens — until
 *     a manual reload fetches a fresh `index.html`. A reload is exactly the
 *     right cure, so this module performs it: retry once, then reload once per
 *     session per chunk, then let the error boundary explain itself.
 *
 * The one-shot guard is deliberate. A reload loop is worse than an error card:
 * if the second attempt after a reload also fails, the failure is not stale
 * caching, and the honest answer is an error message with a button, not an
 * infinite refresh.
 */

/** Which chunk each route needs. Kept here (not in App.jsx) so it can be tested without JSX. */
export const ROUTE_CHUNK = {
  landing: 'landing',
  dashboard: 'dashboard',
  phone: 'phone',
  demo: 'demo',
  privacy: 'static',
  terms: 'static',
  notfound: 'static',
}

/** Every chunk App.jsx must provide an importer for. */
export const CHUNK_NAMES = ['landing', 'dashboard', 'phone', 'demo', 'static']

/** sessionStorage key holding the name of the chunk we already reloaded for. */
export const RELOAD_FLAG = 'hs-chunk-reload'

export const DEFAULT_ATTEMPTS = 2
export const DEFAULT_RETRY_DELAY_MS = 250

/** name -> in-flight or resolved promise, so a preload and a render share one fetch. */
const inFlight = new Map()

function safeStorage() {
  try {
    // Absent in Node (the tests) and throws in some privacy modes.
    return typeof sessionStorage === 'undefined' ? null : sessionStorage
  } catch {
    return null
  }
}

function clearReloadFlag(name, storage = safeStorage()) {
  try {
    if (storage && storage.getItem(RELOAD_FLAG) === name) storage.removeItem(RELOAD_FLAG)
  } catch {
    /* storage unavailable — nothing to clear */
  }
}

/**
 * Reload the page once per chunk per session, and say whether it did.
 *
 * Somewhere to `return false` matters more than it looks: with storage
 * unavailable the guard cannot be remembered, and a reload would then be
 * unbounded. A visible error beats a refresh loop, so that case does not reload.
 */
export function recoverOnce(name, { storage = safeStorage(), reload } = {}) {
  if (!storage) return false
  try {
    if (storage.getItem(RELOAD_FLAG) === name) return false
    storage.setItem(RELOAD_FLAG, name)
  } catch {
    return false
  }
  const fire = reload || (() => {
    if (typeof window !== 'undefined' && window.location) window.location.reload()
  })
  fire()
  return true
}

/**
 * Load a route chunk, once.
 *
 * `importer` is the dynamic `import()`; the promise is memoised so React.lazy,
 * a preload from the nav handler, and a StrictMode double render all share a
 * single network request. A failure is retried once (a flaky connection is the
 * second most common cause), and a final failure calls `onFailure`, which by
 * default reloads once and then rethrows so the error boundary can render.
 */
export function loadChunk(name, importer, options = {}) {
  const {
    attempts = DEFAULT_ATTEMPTS,
    delayMs = DEFAULT_RETRY_DELAY_MS,
    // Same seam as `recoverOnce`: one place decides where the guard is kept.
    storage = safeStorage(),
    onFailure = (error) => {
      recoverOnce(name)
      throw error
    },
    sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  } = options

  if (inFlight.has(name)) return inFlight.get(name)

  const promise = (async () => {
    let lastError
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
      try {
        const module = await importer()
        // A successful load after a recovery reload re-arms the guard: the next
        // deploy gets the same self-healing chance as this one did.
        clearReloadFlag(name, storage)
        return module
      } catch (error) {
        lastError = error
        if (attempt < attempts) await sleep(delayMs * attempt)
      }
    }
    return onFailure(lastError)
  })()

  inFlight.set(name, promise)
  // A rejection must not be remembered, or every later attempt fails instantly
  // from the cache instead of trying the network again.
  promise.catch(() => inFlight.delete(name))
  return promise
}

/** Test seam: forget what has been loaded. */
export function resetChunkCache() {
  inFlight.clear()
}
