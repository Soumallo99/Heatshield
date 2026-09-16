import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import ErrorBoundary from './components/ErrorBoundary'
import './index.css'

/*
 * Service worker registration.
 *
 * PRODUCTION ONLY on purpose: in dev, caching static assets fights Vite's HMR
 * and you end up debugging stale modules. Use `npm run build && npm run preview`
 * to exercise the offline path.
 *
 * sw.js is served from the site root (public/), so its scope covers the whole
 * app. Registering from anywhere else silently limits it to a subdirectory.
 */
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker
      .register('/sw.js', { scope: '/' })
      .then((reg) => {
        // Pick up a new worker as soon as one is waiting, without a full reload.
        if (reg.waiting) reg.waiting.postMessage({ type: 'SKIP_WAITING' })
      })
      .catch((err) => {
        // Offline capability is an enhancement, never a hard failure.
        console.warn('[HeatShield] service worker registration failed:', err)
      })
  })
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
