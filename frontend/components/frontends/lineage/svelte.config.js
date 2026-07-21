import adapter from 'svelte-adapter-bun';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	compilerOptions: { experimental: { async: true } },
	kit: {
		adapter: adapter(),
		// Project-first IA: a STATIC per-app asset prefix so the microfrontends proxy
		// routes this zone's built assets + /@vite in dev.
		paths: { base: '/lineage' },
		experimental: { remoteFunctions: true },
	},
};

export default config;
