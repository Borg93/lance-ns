import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	server: {
		// Same per-domain zone map as the viewer app — the annotator zone talks to
		// the same three services.
		proxy: {
			'/api/annotations': { target: 'http://127.0.0.1:8103', changeOrigin: true },
			'/api/assist': { target: 'http://127.0.0.1:8103', changeOrigin: true },
			'/api/jobs': { target: 'http://127.0.0.1:8103', changeOrigin: true },
			'/api/search': { target: 'http://127.0.0.1:8102', changeOrigin: true },
			'/api': { target: 'http://127.0.0.1:8101', changeOrigin: true },
		},
	},
});
