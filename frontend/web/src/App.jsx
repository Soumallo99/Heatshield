import { lazy, Suspense, useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import HeatField from './components/HeatField'
import { CHUNK_NAMES, loadChunk, ROUTE_CHUNK } from './lazyRoute'
import { EASE } from './motion'
import pageMeta from './site-pages.json'
import { anchorFromHash, resolveRoute, routeForTarget } from './routes'

// Route-level chunks protect a phone cold-open from the dense operations
// console (and its chart/map helpers). The map itself remains lazy inside the
// dashboard, so no Leaflet code is fetched for citizen use.
//
// Every importer goes through `loadChunk`: one memoised fetch per chunk, retried
// once, and — if the chunk is genuinely gone — a single automatic reload, which
// is the cure for the stale-deploy case that used to make the Citizen tab
// unopenable until somebody reloaded by hand. Keying them by name also lets a
// tab press start its own download before the route changes.
const CHUNK_IMPORTERS = {
  landing: () => import('./components/Landing'),
  dashboard: () => import('./components/Dashboard'),
  phone: () => import('./mobile/PhoneApp'),
  // The demo ships in its own chunk: cold-opening Overview or Citizen never pays
  // for demo code, and the demo never needs the live API.
  demo: () => import('./demo/DemoApp'),
  // Privacy, Terms and the 404 page are text; they share one chunk for the same
  // reason, since a phone cold-open should not download a legal document.
  static: () => import('./components/StaticPage'),
}

for (const name of Object.values(ROUTE_CHUNK)) {
  if (!CHUNK_IMPORTERS[name]) throw new Error(`routes.js sends a visitor to the "${name}" chunk, which has no importer`)
}
for (const name of CHUNK_NAMES) {
  if (!CHUNK_IMPORTERS[name]) throw new Error(`chunk "${name}" is declared but has no importer`)
}

const Landing = lazy(() => loadChunk('landing', CHUNK_IMPORTERS.landing))
const Dashboard = lazy(() => loadChunk('dashboard', CHUNK_IMPORTERS.dashboard))
const PhoneApp = lazy(() => loadChunk('phone', CHUNK_IMPORTERS.phone))
const DemoApp = lazy(() => loadChunk('demo', CHUNK_IMPORTERS.demo))
const StaticPage = lazy(() => loadChunk('static', CHUNK_IMPORTERS.static))

/**
 * Minimal hash router.
 *
 * Deliberately not react-router: three routes, and a hand-rolled router keeps the
 * dependency list small. Hash routing also survives being served from any static
 * host or file path without server rewrites.
 *
 * Page transitions use a short cross-dissolve plus a small opposing vertical
 * offset — the outgoing page lifts away as the incoming one rises, which reads as
 * one continuous movement rather than two separate fades.
 */
function useRoute() {
  // Routing lives in ./routes.js so it can be tested without a browser
  // (scripts/test-routes.mjs); this hook only wires it to the hashchange event.
  const readRoute = () => resolveRoute(window.location.hash)
  const [route, setRoute] = useState(readRoute)

  // In-page anchors (`#/#sources`) are the browser's job normally, but here the
  // fragment is `/#sources`, which matches no element id — so the scroll is
  // explicit, after a paint so the target section is mounted.
  const scrollToAnchor = () => {
    const anchor = anchorFromHash(window.location.hash)
    if (!anchor) return
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    // The target may not exist yet: every page is a lazy chunk, so a link from
    // the 404 page arrives here before Landing has mounted. One frame is not
    // enough — keep looking for about a second, then give up quietly rather than
    // scrolling to the top (which would look like the link did nothing).
    let tries = 0
    const seek = () => {
      const target = document.getElementById(anchor)
      if (target) {
        target.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' })
        return
      }
      if (tries < 60) {
        tries += 1
        requestAnimationFrame(seek)
      }
    }
    requestAnimationFrame(seek)
  }

  useEffect(() => {
    const onChange = () => {
      const anchor = anchorFromHash(window.location.hash)
      setRoute(readRoute())
      if (anchor) {
        scrollToAnchor()
        return
      }
      // Each page starts at its own top. Without this, clicking Citizen from
      // the bottom of the long dashboard lands you in the new page's empty
      // scroll tail, which reads as "the tab didn't open".
      window.scrollTo(0, 0)
    }
    // A deep link straight into a section must land there on first paint too.
    if (anchorFromHash(window.location.hash)) scrollToAnchor()
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])

  // Each page carries its own title and description. For a crawler the static
  // index.html is the landing page (hash routing cannot change that), but for a
  // reader — and for the browser tab, and for a shared link — the title must say
  // where you are, and the 404 must not claim to be the home page.
  useEffect(() => {
    const meta = pageMeta[route] || pageMeta.notfound
    document.title = meta.title
    const description = document.querySelector('meta[name="description"]')
    // The static index.html describes the landing page; a hash-routed 404 must
    // not leave that description in the head while showing "not found".
    if (description) description.setAttribute('content', meta.description)
  }, [route])

  // The chunk request goes out *before* the hash changes, so the download
  // overlaps the re-render instead of starting after it.
  return { route, go: (r) => { startRouteChunk(r); window.location.hash = `#/${r}` } }
}

/**
 * Start the chunk a navigation target needs, without waiting for it.
 *
 * The target is a hash key ('dashboard', '' for the Overview button), so it goes
 * through `routeForTarget` first: `ROUTE_CHUNK['']` is undefined and the preload
 * would be skipped for exactly the button that returns a citizen to the front page.
 */
function startRouteChunk(target) {
  const name = ROUTE_CHUNK[target] ?? ROUTE_CHUNK[routeForTarget(target)]
  if (name) loadChunk(name, CHUNK_IMPORTERS[name]).catch(() => undefined)
}

export default function App() {
  const { route, go } = useRoute()

  return (
    <div className="grain relative min-h-screen">
      <HeatField />

      {/*
        Enter-only transition, deliberately. This used to be
        `AnimatePresence mode="wait"`, which does not mount the incoming page
        until the outgoing one has animated away — so pressing a tab waited out
        an animation before it even asked for the next page's code, and a
        reload was the only way through when that fetch then failed. Now the new
        page mounts at once and fades in over the old one: the same 0.5 s of
        motion, without depending on an animation completing first.
      */}
      <motion.div
        key={route}
        className="relative z-10"
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: EASE }}
      >
        <Suspense fallback={<div className="relative z-10 grid min-h-screen place-items-center text-[12px] text-white/50">Opening HeatShield…</div>}>
          {route === 'dashboard' ? (
            <Dashboard onExit={() => go('')} onDemo={() => go('demo')} />
          ) : route === 'phone' ? (
            <PhoneApp onExit={() => go('dashboard')} />
          ) : route === 'demo' ? (
            <DemoApp onExit={() => go('')} />
          ) : route === 'privacy' || route === 'terms' ? (
            <StaticPage page={route} />
          ) : route === 'notfound' ? (
            <StaticPage page="notfound" />
          ) : (
            <Landing onEnter={() => go('dashboard')} onDemo={() => go('demo')} />
          )}
        </Suspense>
      </motion.div>

      {/* The phone route carries its own thumb-reachable navigation; the demo
          route carries its own top-level controls. */}
      {route !== 'phone' && route !== 'demo' && <motion.nav
        className="fixed bottom-5 left-1/2 z-40 -translate-x-1/2"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.5 }}
      >
        <div className="flex gap-1 rounded-full border border-white/12 bg-ink-950/80 p-1 backdrop-blur-md">
          {[
            ['', 'Overview'],
            ['dashboard', 'Operations'],
            ['phone', 'Citizen'],
            ['demo', 'Heat Demo'],
          ].map(([r, label]) => (
            <button
              key={r}
              onClick={() => go(r)}
              className="relative rounded-full px-4 py-1.5 text-[11.5px] transition"
            >
              {route === r && (
                <motion.span
                  layoutId="routeTab"
                  className="absolute inset-0 rounded-full bg-white/[.13]"
                  transition={{ type: 'spring', stiffness: 320, damping: 30 }}
                />
              )}
              <span className="relative" style={{ color: route === r ? '#fff' : 'rgba(255,255,255,.45)' }}>
                {label}
              </span>
            </button>
          ))}
        </div>
      </motion.nav>}

      {/* mobile entry hint on the dashboard */}
      {route === 'dashboard' && (
        <motion.button
          onClick={() => go('phone')}
          className="fixed right-5 top-[68px] z-30 rounded-full border border-white/12 bg-ink-900/95 px-4 py-2 text-[11.5px] transition hover:border-white/30"
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.6, ease: EASE, delay: 0.7 }}
          whileHover={{ scale: 1.04 }}
          whileTap={{ scale: 0.96 }}
        >
          📱 Citizen view
        </motion.button>
      )}
    </div>
  )
}
