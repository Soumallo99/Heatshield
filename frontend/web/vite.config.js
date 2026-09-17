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
    // Raise the warning limit: the ward GeoJSON-driven chunks are intentional
    // and already split below.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // Split the heavy vendors so the landing page doesn't pay for the map.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined
          if (id.includes('leaflet')) return 'leaflet'
          if (id.includes('framer-motion')) return 'motion'
          if (id.includes('react-router') || id.includes('/react-dom/') ||
              id.includes('/react/') || id.includes('scheduler')) return 'react'
          return 'vendor'
        },
      },
    },
  },
})
