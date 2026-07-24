import { defineConfig } from 'vitest/config';

export default defineConfig({
	test: {
		include: ['src/**/*.test.ts'],
		environment: 'node',
		// zod 3.25 re-exports `z` as a namespace (`import * as z; export { z }`);
		// vitest's runner mishandles that unless zod is transformed through Vite.
		server: { deps: { inline: ['valibot'] } },
	},
	resolve: {
		alias: { $lib: new URL('./src/lib', import.meta.url).pathname },
	},
});
