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
		// No /api dev proxy anymore: the zone's own BFF routes (src/routes/api/**) serve
		// `${base}/api/*` in dev and prod alike, defaulting to the three local lance-media
		// services (VIEWER_API :8101 · SEARCH_API :8102 · ANNOTATOR_API :8103).
		proxy: {
			// Zone composition: the annotator app owns /annotator (micro-frontends
			// routing-based zones) — one origin, path-routed to the sibling app.
			'/annotator': { target: 'http://127.0.0.1:5176', changeOrigin: true, ws: true },
		},
	},
});
