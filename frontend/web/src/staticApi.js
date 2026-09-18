/**
 * Shared static-snapshot plumbing for every browser surface (citizen phone
 * brief, Heat Risk Demo, Delhi NCR ops). One copy — previously duplicated in
 * three files.
 *
 * All paths stay project-relative (`./`) so a GitHub Pages deployment under
 * `https://<owner>.github.io/Heatshield/` keeps working, and browser code
 * never hard-codes an absolute origin.
 */

const BASE_PATH = import.meta.env?.BASE_URL || './'

/**
 * URL of anything copied verbatim from `public/` — the ward GeoJSON, an icon,
 * a generated snapshot. Never a document-root path: this app is deployed under
 * a repository subdirectory on GitHub Pages (`/Heatshield/`), where `/data/…`
 * escapes the app and 404s.
 */
export const publicURL = (name) => `${BASE_PATH.replace(/\/?$/, '/')}${name.replace(/^\//, '')}`

/** URL of a generated snapshot in `public/static-api/`. */
export const staticURL = (name) => publicURL(`static-api/${name}`)

/**
 * True when there is no FastAPI proxy worth asking first: a `file://` open, a
 * `*.github.io` Pages host, or an explicit `?static` override. Going straight
 * to the generated snapshot there prevents deliberate 404s at every cold open.
 */
export function isStaticHost() {
  if (typeof window === 'undefined') return false
  const host = window.location.hostname
  return (
    window.location.protocol === 'file:' ||
    host.endsWith('.github.io') ||
    new URLSearchParams(window.location.search).has('static')
  )
}

/**
 * fetch + JSON with honest errors. `ErrorClass` lets each surface keep its own
 * named error type (PhoneDataError / DemoDataError) without duplicating the
 * logic. AbortError is re-thrown untouched so callers can ignore unmounts.
 */
/**
 * Deadlines for every browser fetch.
 *
 * Without one, a fetch against a host that accepts the TCP connection but never
 * answers sits there until the OS gives up (minutes), and the UI shows a
 * skeleton forever — indistinguishable from "still loading" on a phone with one
 * bar of signal. Every request now carries a deadline: the caller's own
 * unmount signal still wins (AbortError passes through untouched so callers can
 * keep ignoring it), a deadline abort is converted into an honest, typed error.
 */
export const REQUEST_TIMEOUT_MS = 15000

export function withTimeout(signal, ms = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, ms)
  const relay = () => controller.abort()
  if (signal) {
    if (signal.aborted) controller.abort()
    else signal.addEventListener('abort', relay, { once: true })
  }
  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup() {
      clearTimeout(timer)
      signal?.removeEventListener('abort', relay)
    },
  }
}

export async function readJSON(url, signal, ErrorClass = Error, { timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
  const guard = withTimeout(signal, timeoutMs)
  try {
    let response
    try {
      response = await fetch(url, { headers: { Accept: 'application/json' }, signal: guard.signal })
    } catch (error) {
      if (guard.timedOut()) throw new ErrorClass(`${url} did not answer within ${timeoutMs / 1000}s`)
      if (error?.name === 'AbortError') throw error
      throw new ErrorClass(`Unable to reach ${url}`)
    }
    if (!response.ok) throw new ErrorClass(`${url} returned ${response.status}`)
    try {
      // The deadline deliberately still applies here. A server that sends
      // headers and then trickles the body (or stops mid-stream) is the same
      // hang from the user's side; clearing the timer after the headers would
      // leave the spinner running forever.
      return await response.json()
    } catch (error) {
      if (guard.timedOut()) throw new ErrorClass(`${url} did not finish answering within ${timeoutMs / 1000}s`)
      if (error?.name === 'AbortError') throw error
      throw new ErrorClass(`${url} returned invalid JSON`)
    }
  } finally {
    guard.cleanup()
  }
}