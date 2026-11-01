import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig(({ mode }) => {
 const env = loadEnv(mode, '..', 'PAIR_AKI_')
 return {
  plugins: [react()], base: './', build: { sourcemap: false },
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api/competition/v2': { target: env.PAIR_AKI_API_TARGET || 'http://127.0.0.1:30886', changeOrigin: false } },
  },
}
})
