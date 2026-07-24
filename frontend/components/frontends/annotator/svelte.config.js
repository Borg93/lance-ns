import adapter from 'svelte-adapter-bun';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Enables `await` directly inside Svelte templates and load functions.
		// Useful for streaming search results progressively.
		experimental: {
			async: true,
		},
	},
	preprocess: vitePreprocess(),
	kit: {
		// Zone base: this zone owns /annotator behind the lance ingress (renamed
		// from the standalone repo's /annotate to match the zone-dir = base-path
		// convention). The workspace-patched svelte-adapter-bun serves assets at
		// the based path too (/annotator/_app/…), so no base-stripping proxy is
		// needed. `relative: false` keeps asset URLs absolute, trailing-slash-proof.
		paths: { base: '/annotator', relative: false },
		// Bun-server output — the rask MFE build target (`svelte-adapter-bun`).
		// The app stays client-rendered (`ssr = false` in src/routes/+layout.ts):
		// the Bun server serves the shell + assets, the browser renders (WebGPU,
		// localStorage, etc. never run server-side). `/api/*` is not this server's
		// concern — dev proxies it (vite.config.ts), prod routes it at the gateway.
		adapter: adapter(),
		alias: {
			$lib: './src/lib',
			'$lib/*': './src/lib/*',
		},
	},
};

export default config;
