import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '..', 'API_');
  return {
    plugins: [react()],
    build: { rollupOptions: { output: { manualChunks(id) {
      if (id.includes('/node_modules/zrender/')) return 'chart-renderer';
      if (id.includes('/node_modules/echarts/')) return 'echarts';
    } } } },
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target: process.env.API_PROXY_TARGET ?? env.API_PROXY_TARGET ?? 'http://localhost:8000', ws: true } },
    },
  };
});
