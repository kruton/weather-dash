import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'
import { patchCssModules } from 'vite-css-modules'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    patchCssModules({
      generateSourceTypes: true,
    }),
    react(),
  ],
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  },
})
