import { resolve } from 'node:path'
import { defineConfig } from 'vite'

// Two pages: the site (index) and the operator console. In production the
// core serves both from the same origin, so /api needs no CORS.
export default defineConfig({
  base: process.env.BASE ?? '/',
  server: {
    port: 5179,
    strictPort: true,
    proxy: { '/api': { target: 'http://localhost:8080', ws: true } },
  },
  build: {
    target: 'es2023',
    rollupOptions: { input: { site: resolve(import.meta.dirname, 'index.html'), console: resolve(import.meta.dirname, 'console.html') } },
  },
})
