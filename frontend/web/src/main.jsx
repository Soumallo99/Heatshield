import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { warn } from './log'
import ErrorBoundary from './components/ErrorBoundary'
import './index.css'

/*
 * Service worker lifecycle.
 *
 * PRODUCTION registers; DEVELOPMENT unregisters. Both halves matter:
 *
 *   * registering is what makes the phone app installable and offline-capable;
 *     sw.js is served beside index.html and a relative scope keeps a GitHub
 *     Pages project subdirectory (/Heatshield/) working;
 *   * not registering in dev is deliberate — caching static assets fights
 *     Vite's HMR and you end up debugging stale modules;
 *   * the dev branch also *removes* a worker an earlier prod-mode session left
 *     behind, along with its caches. Otherwise a developer sits on an old build
 *     while the dev server looks healthy.
 *
 * This block lives here, in a module, rather than inline in index.html so the
 * page needs no `'unsafe-inline'` in its Content-Security-Policy — inline
 * scripts are exactly what an injected script would use. See index.html.
 */
if ('serviceWorker' in navigator) {
  // Did a worker already control this page when it loaded? A FIRST visit has no
  // controller, and `clients.claim()` in the worker's activate step fires
  // `controllerchange` then too — refreshing on that would reload every new
  // visitor's first page for no reason at all.
  const wasControlled = Boolean(navigator.serviceWorker.controller)

  window.addEventListener('load', () => {
    if (import.meta.env.PROD) {
      // A deploy while somebody has the app open leaves a new worker waiting:
      // the pages already loaded keep running the old build, and its chunk
      // filenames are gone from the server. Promote the waiting worker the
      // moment it finishes installing instead of waiting for every tab to close,
      // then reload once so the running code matches what the server has.
      const promote = (worker) => worker?.postMessage({ type: 'SKIP_WAITING' })
      navigator.serviceWorker
        .register('./sw.js', { scope: './' })
        .then((reg) => {
          if (reg.waiting) promote(reg.waiting)
          reg.addEventListener('updatefound', () => {
            const installing = reg.installing
            installing?.addEventListener('statechange', () => {
              if (installing.state === 'installed' && navigator.serviceWorker.controller) promote(installing)
            })
          })
        })
        .catch((err) => {
          // Offline capability is an enhancement, never a hard failure.
          warn(`service worker registration failed: ${err?.message || err}`)
        })

      // Refresh at most once per page load, and not while somebody is typing:
      // the subscriber box is the only place a reload mid-entry would cost a
      // person their input. If a field has focus, look again shortly.
      let refreshed = false
      const typing = () => /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')
      const refreshForNewBuild = () => {
        if (refreshed || !wasControlled) return
        if (typing()) {
          setTimeout(refreshForNewBuild, 2000)
          return
        }
        refreshed = true
        window.location.reload()
      }
      navigator.serviceWorker.addEventListener('controllerchange', refreshForNewBuild)
      return
    }
    navigator.serviceWorker
      .getRegistrations()
      .then((registrations) => registrations.forEach((reg) => reg.unregister()))
      .catch(() => {})
    if ('caches' in window) {
      caches
        .keys()
        .then((keys) => keys.forEach((key) => caches.delete(key)))
        .catch(() => {})
    }
  })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
