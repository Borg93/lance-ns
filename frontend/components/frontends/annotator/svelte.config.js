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
    // Zone base: this app owns /annotate. DEV (vite) honors the base fully, so
    // the viewer dev proxy forwards /annotate verbatim. PROD (svelte-adapter-bun)
    // has a quirk — it serves based PAGES (/annotate/) but BARE assets (/_app/) —
    // so the prod proxy strips /annotate only for /annotate/_app/* (see the two
    // server.ts). `relative: false` keeps asset URLs absolute (/annotate/_app/…),
    // trailing-slash-proof. (micro-frontends skill: routing-based zones.)
    paths: { base: '/annotate', relative: false },
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
