import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
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
  window.addEventListener('load', () => {
    if (import.meta.env.PROD) {
      navigator.serviceWorker
        .register('./sw.js', { scope: './' })
        .then((reg) => {
          // Pick up a new worker as soon as one is waiting, without a full reload.
          if (reg.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' })
        })
        .catch((err) => {
          // Offline capability is an enhancement, never a hard failure.
          console.warn('[HeatShield] service worker registration failed:', err)
        })
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
