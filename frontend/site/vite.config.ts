import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  root: 'site',
  plugins: [react()],
  build: { outDir: 'dist' },
  server: { host: '127.0.0.1', port: 5174, proxy: { '/api/public': 'http://127.0.0.1:8766' } },
})
