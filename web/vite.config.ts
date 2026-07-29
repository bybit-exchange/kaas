/// <reference types="vitest" />
import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { visualizer } from 'rollup-plugin-visualizer'
import path from 'path'

export default defineConfig({
  plugins: [
    tailwindcss(),
    react(),
    ...(process.env.ANALYZE === 'true'
      ? [visualizer({ open: true, gzipSize: true, filename: 'dist/stats.html' })]
      : []),
  ],
  build: {
    chunkSizeWarningLimit: 500,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (
            id.includes('node_modules/react-dom') ||
            id.includes('node_modules/react/') ||
            id.includes('node_modules/react-router') ||
            id.includes('node_modules/scheduler')
          ) {
            return 'vendor-react'
          }
          if (
            id.includes('node_modules/react-markdown') ||
            id.includes('node_modules/remark-') ||
            id.includes('node_modules/rehype-') ||
            id.includes('node_modules/highlight.js') ||
            id.includes('node_modules/unified') ||
            id.includes('node_modules/unist-') ||
            id.includes('node_modules/mdast-') ||
            id.includes('node_modules/hast-') ||
            id.includes('node_modules/micromark') ||
            id.includes('node_modules/devlop') ||
            id.includes('node_modules/decode-named-character-reference') ||
            id.includes('node_modules/character-entities')
          ) {
            return 'vendor-markdown'
          }
          if (id.includes('node_modules/@radix-ui')) {
            return 'vendor-radix'
          }
          if (
            id.includes('node_modules/zustand') ||
            id.includes('node_modules/sonner') ||
            id.includes('node_modules/lucide-react') ||
            id.includes('node_modules/class-variance-authority') ||
            id.includes('node_modules/clsx') ||
            id.includes('node_modules/tailwind-merge')
          ) {
            return 'vendor-misc'
          }
        },
      },
    },
  },
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, _req, res) => {
            res.setHeader('X-Accel-Buffering', 'no')
            res.setHeader('Cache-Control', 'no-cache')
            res.setHeader('Connection', 'keep-alive')
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    globals: true,
  },
})
