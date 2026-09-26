import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// В dev-режиме /api проксируется на локальный backend (uvicorn на :8000).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
      '/health': process.env.VITE_API_PROXY ?? 'http://localhost:8000',
    },
  },
});
