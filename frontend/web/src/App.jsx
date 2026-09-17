import { lazy, Suspense, useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import HeatField from './components/HeatField'

// Route-level chunks protect a phone cold-open from the dense operations
// console (and its chart/map helpers). The map itself remains lazy inside the
// dashboard, so no Leaflet code is fetched for citizen use.
const Landing = lazy(() => import('./components/Landing'))
const Dashboard = lazy(() => import('./components/Dashboard'))
const PhoneApp = lazy(() => import('./mobile/PhoneApp'))
// The demo ships in its own chunk: cold-opening Overview or Citizen never pays
// for demo code, and the demo never needs the live API.
const DemoApp = lazy(() => import('./demo/DemoApp'))
import { EASE } from './motion'

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
const ROUTES = { '': 'landing', dashboard: 'dashboard', mobile: 'phone', phone: 'phone', demo: 'demo' }

function useRoute() {
  const readRoute = () => ROUTES[window.location.hash.replace('#/', '') || ''] || ''
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const onChange = () => {
      setRoute(readRoute())
      // Each page starts at its own top. Without this, clicking Citizen from
      // the bottom of the long dashboard lands you in the new page's empty
      // scroll tail, which reads as "the tab didn't open".
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return { route: ROUTES[route] ? route : '', go: (r) => { window.location.hash = `#/${r}` } }
}

export default function App() {
  const { route, go } = useRoute()

  return (
    <div className="grain relative min-h-screen">
      <HeatField />

      <AnimatePresence mode="wait">
        <motion.div
          key={route}
          className="relative z-10"
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -14 }}
          transition={{ duration: 0.5, ease: EASE }}
        >
          <Suspense fallback={<div className="relative z-10 grid min-h-screen place-items-center text-[12px] text-white/50">Opening HeatShield…</div>}>
            {route === 'dashboard' ? (
              <Dashboard onExit={() => go('')} onDemo={() => go('demo')} />
            ) : route === 'phone' ? (
              <PhoneApp onExit={() => go('dashboard')} />
            ) : route === 'demo' ? (
              <DemoApp onExit={() => go('')} />
            ) : (
              <Landing onEnter={() => go('dashboard')} onDemo={() => go('demo')} />
            )}
          </Suspense>
        </motion.div>
      </AnimatePresence>

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
