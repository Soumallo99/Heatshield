/**
 * Hash-router truth table, deliberately outside App.jsx.
 *
 * Two rules that are easy to get wrong and were wrong once:
 *   • an unknown hash is a 404, not the landing page — otherwise a mistyped or
 *     dead link silently "works" and the visitor believes the page exists;
 *   • a query string (`#/phone?static`) is not part of the route.
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

export function resolveRoute(hash) {
  const key = String(hash ?? '').replace(/^#\/?/, '').replace(/\?.*$/, '')
  if (key === '') return 'landing'
  return ROUTES[key] || 'notfound'
}
