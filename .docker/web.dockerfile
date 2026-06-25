# syntax=docker/dockerfile:1.11
# Lance Lineage web UI — SvelteKit (Svelte Flow + bits-ui) on Bun. Build context = repo root.
FROM oven/bun:1.3-slim AS build
WORKDIR /app
COPY web/package.json web/bun.lock ./
RUN --mount=type=cache,target=/root/.bun/install/cache bun install --frozen-lockfile
COPY web/ ./
RUN bun run build

FROM oven/bun:1.3-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000
COPY --from=build /app/build ./build
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
EXPOSE 3000
# Bun is the init/PID1 here; the slim image has no curl, so health-check via bun's fetch.
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD bun -e "fetch('http://localhost:'+ (process.env.PORT||3000)).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
USER bun
ENTRYPOINT ["bun", "./build/index.js"]
