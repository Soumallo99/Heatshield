import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API port is overridable (HS_API_PORT) so a laptop with :8000 taken can
// move the whole stack. The proxy must follow the same value, or /api/* would
// keep pointing at a dead port while the API runs elsewhere.
const API_TARGET = `http://127.0.0.1:${process.env.HS_API_PORT || 8000}`

export default defineConfig({
  // Relative assets are essential on GitHub Pages, where this project is served
  // below /Heatshield/ rather than at a domain root. Set VITE_BASE_PATH when a
  // deployment intentionally has a known absolute prefix.
  base: process.env.VITE_BASE_PATH || './',
  plugins: [react()],
  // Cesium is imported only by the lazy globe chunk. Pre-bundling it up front
  // stops Vite from discovering it mid-session and reloading the page.
  optimizeDeps: { include: ['cesium'] },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    // allow the sandbox preview host (https://{port}-{id}.e2b.app)
    allowedHosts: true,
    proxy: {
      // browser calls /api/... -> FastAPI (never call localhost from the client)
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  // Production preview (PWA/offline testing). Different port from `dev`, and
  // it needs the same /api proxy — the built app makes identical relative calls.
  preview: {
    host: '0.0.0.0',
    port: 4173,
    allowedHosts: true,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    // The 4 MB Cesium chunk is intentional and lazy-only: it is reached solely
    // through the "3D globe" toggle, and the constraint that actually matters
    // (the citizen phone cold-open) is enforced in bytes by
    // scripts/check_phone_budget.mjs plus tests/test_globe_view.py. Leaving the
    // limit at 700 kB would print the same warning on every build until people
    // stop reading build output.
    chunkSizeWarningLimit: 4500,
    rollupOptions: {
      output: {
        // Split the heavy vendors so the landing page doesn't pay for the map.
        manualChunks(id) {
          // Vite's own runtime helpers (\0vite/preload-helper, commonjsHelpers)
          // are shared between the entry and every lazily-imported chunk. Give
          // them their own home: otherwise Rollup parks them in the chunk that
          // now has to be loaded by everyone — and when that chunk is the 1 MB
          // Cesium chunk, the citizen phone route downloads the whole globe
          // bundle to run a 1 KB helper. (This is exactly how the phone budget
          // gate caught the first attempt at this integration.)
          // Only Vite's own virtual runtime modules — NOT \0commonjsHelpers,
          // which is shared with the React chunk and would create a
          // react <-> helpers chunk cycle.
          if (id.startsWith('\0vite/')) return 'vite-helpers'
          if (!id.includes('node_modules')) return undefined
          // CesiumJS is ~1 MB gzipped: it belongs to the globe chunk alone, so
          // the 2D map, the dashboard and (above all) the citizen phone route
          // never fetch it. See src/globe/ and scripts/check_phone_budget.mjs.
          // `nosleep.js` is a Cesium widget dependency whose bundle carries
          // ~12 kB of base64 "silent video" for the screen wake lock. It does
          // not match 'cesium' by path, so without this it falls into the
          // shared chunk every route imports — i.e. the phone pays for the
          // globe's wake-lock video. Caught by the budget gate, twice.
          if (id.includes('cesium') || id.includes('nosleep')) return 'cesium'
          if (id.includes('leaflet')) return 'leaflet'
          if (id.includes('framer-motion')) return 'motion'
          if (id.includes('react-router') || id.includes('/react-dom/') ||
              id.includes('/react/') || id.includes('scheduler')) return 'react'
          // No catch-all 'vendor' bucket: the globe drags a whole dependency
          // closure in (protobufjs, draco3d, pako, …) that only the lazy globe
          // chunk uses. A catch-all would force those megabytes into a chunk
          // the entry HTML references, i.e. straight into the citizen phone
          // cold-open. Let Rollup keep everything else with its only importer.
          return undefined
        },
      },
    },
  },
})
