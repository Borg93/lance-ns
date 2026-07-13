import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		// Dev convenience: proxy API calls to the lineage service so the browser stays same-origin.
		proxy: {
			"/api": {
				target: process.env.LINEAGE_API ?? "http://localhost:8001",
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/api/, ""),
			},
		},
	},
});
