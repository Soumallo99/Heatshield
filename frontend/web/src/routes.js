/**
 * Hash-router truth table, deliberately outside App.jsx.
 *
 * Three rules that are easy to get wrong and two of which were wrong once:
 *   • an unknown hash is a 404, not the landing page — otherwise a mistyped or
 *     dead link silently "works" and the visitor believes the page exists;
 *   • a query string (`#/phone?static`) is not part of the route;
 *   • an in-page anchor is not a route. `#/#sources` (the footer's "Sources"
 *     link) must open the landing page at its sources section, not a 404 —
 *     anchors and routes share one hash, so the router has to know the
 *     difference.
 *
 * Keeping it a pure function means the mapping can be tested in plain Node
 * (`scripts/test-routes.mjs`) instead of only by clicking around a browser.
 */
export const ROUTES = {
  '': 'landing',
  dashboard: 'dashboard',
  mobile: 'phone',
  phone: 'phone',
  demo: 'demo',
  privacy: 'privacy',
  terms: 'terms',
}

/** Section ids that live inside the landing page. */
export const LANDING_ANCHORS = ['sources']

export function resolveRoute(hash) {
  const raw = String(hash ?? '').replace(/^#/, '').replace(/\?.*$/, '')
  if (!raw.startsWith('/')) return 'landing'          // '#sources' — a bare anchor
  const key = raw.replace(/^\//, '')
  if (key === '') return 'landing'
  if (key.startsWith('#')) return 'landing'           // '#/#sources' — anchored landing
  return ROUTES[key] || 'notfound'
}

/**
 * The section a link asked for, or null. The fragment cannot be left to the
 * browser here: `#/#sources` means the fragment is `/#sources`, which will
 * never match an element id.
 */
export function anchorFromHash(hash) {
  const match = /#([A-Za-z][\w-]*)$/.exec(String(hash ?? ''))
  return match ? match[1] : null
}
