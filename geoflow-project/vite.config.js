import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  build: {
    chunkSizeWarningLimit: 1200, // maplibre-gl alone is ~1 MB, loaded lazily
    rollupOptions: {
      output: {
        // React Flow gets its own long-cached chunk; maplibre is split out by the lazy Map tab import.
        manualChunks: { flow: ['@xyflow/react'] },
      },
    },
  },
});
