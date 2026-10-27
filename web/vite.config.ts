import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const api = 'http://127.0.0.1:7788'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5178,
    proxy: { '/api': api, '/files': api, '/skills': api },
  },
  build: { chunkSizeWarningLimit: 1500 },
})
