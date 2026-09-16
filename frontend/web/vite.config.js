import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    // allow the sandbox preview host (https://{port}-{id}.e2b.app)
    allowedHosts: true,
    proxy: {
      // browser calls /api/... -> FastAPI on :8000 (never call localhost from the client)
      '/api': {
        target: 'http://127.0.0.1:8000',
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
        target: 'http://127.0.0.1:8000',
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
