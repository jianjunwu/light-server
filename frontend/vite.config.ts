import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  base: '/ui/static/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    assetsInlineLimit: 409600,
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/ui/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/v2': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
