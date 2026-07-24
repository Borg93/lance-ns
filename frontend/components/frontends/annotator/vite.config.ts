import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	// No /api dev proxy anymore: the zone's own BFF routes (src/routes/api/**) serve
	// `${base}/api/*` in dev and prod alike, defaulting to the three local lance-media
	// services (VIEWER_API :8101 · SEARCH_API :8102 · ANNOTATOR_API :8103).
});
