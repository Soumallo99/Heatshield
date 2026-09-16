import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import HeatField from './components/HeatField'
import Landing from './components/Landing'
import Dashboard from './components/Dashboard'
import Mobile from './components/Mobile'
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
const ROUTES = { '': 'landing', dashboard: 'dashboard', mobile: 'mobile' }

function useRoute() {
  const [route, setRoute] = useState(() => window.location.hash.replace('#/', '') || '')
  useEffect(() => {
    const onChange = () => setRoute(window.location.hash.replace('#/', '') || '')
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
          {route === 'dashboard' ? (
            <Dashboard onExit={() => go('')} />
          ) : route === 'mobile' ? (
            <Mobile onExit={() => go('dashboard')} />
          ) : (
            <Landing onEnter={() => go('dashboard')} />
          )}
        </motion.div>
      </AnimatePresence>

      {/* persistent route switcher */}
      <motion.nav
        className="fixed bottom-5 left-1/2 z-40 -translate-x-1/2"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease: EASE, delay: 0.5 }}
      >
        <div className="flex gap-1 rounded-full border border-white/12 bg-ink-950/80 p-1 backdrop-blur-md">
          {[
            ['', 'Overview'],
            ['dashboard', 'Operations'],
            ['mobile', 'Citizen'],
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
      </motion.nav>

      {/* mobile entry hint on the dashboard */}
      {route === 'dashboard' && (
        <motion.button
          onClick={() => go('mobile')}
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
