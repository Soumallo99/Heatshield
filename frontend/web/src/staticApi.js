/**
 * Shared static-snapshot plumbing for every browser surface (citizen phone
 * brief, Heat Risk Demo, Delhi NCR ops). One copy — previously duplicated in
 * three files.
 *
 * All paths stay project-relative (`./`) so a GitHub Pages deployment under
 * `https://<owner>.github.io/Heatshield/` keeps working, and browser code
 * never hard-codes an absolute origin.
 */

const BASE_PATH = import.meta.env.BASE_URL || './'

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
export async function readJSON(url, signal, ErrorClass = Error) {
  let response
  try {
    response = await fetch(url, { headers: { Accept: 'application/json' }, signal })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ErrorClass(`Unable to reach ${url}`)
  }
  if (!response.ok) throw new ErrorClass(`${url} returned ${response.status}`)
  try {
    return await response.json()
  } catch {
    throw new ErrorClass(`${url} returned invalid JSON`)
  }
}
