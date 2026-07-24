import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  // OpenCV.js is dynamically imported by the scissors/magnetic tools (8MB wasm,
  // lazy-loaded on first activation). Prebundle it at server start — otherwise the
  // first in-session import triggers a dep re-optimize + full page reload mid-annotation.
  optimizeDeps: {
    include: ['@techstark/opencv-js'],
  },
  server: {
    // During `bun run dev`, proxy /api/* to the three lance-media services by
    // path — the routing-based (zones) composition seam from the micro-frontends
    // skill: annotator owns the write plane, search owns retrieval, viewer owns
    // the rest. Production goes through frontend/server.ts with the same map.
    proxy: {
      // Zone composition: the annotator app owns /annotate (micro-frontends
      // routing-based zones) — one origin, path-routed to the sibling app.
      '/annotate': { target: 'http://127.0.0.1:5176', changeOrigin: true, ws: true },
      '/api/annotations': { target: 'http://127.0.0.1:8103', changeOrigin: true },
      '/api/assist': { target: 'http://127.0.0.1:8103', changeOrigin: true },
      '/api/jobs': { target: 'http://127.0.0.1:8103', changeOrigin: true },
      '/api/search': { target: 'http://127.0.0.1:8102', changeOrigin: true },
      '/api': { target: 'http://127.0.0.1:8101', changeOrigin: true },
    },
  },
});
