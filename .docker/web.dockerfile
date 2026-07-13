# syntax=docker/dockerfile:1.11
# Lance Lineage web UI — SvelteKit (Svelte Flow + bits-ui) on Bun. Build context = repo root.

# ── build: install deps + compile the SvelteKit node build ─────────────────────
FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04 AS build
WORKDIR /app
# Turborepo workspace (Batch 12, rask microfrontend shape): manifests first for the install cache…
COPY frontend/package.json frontend/bun.lock frontend/turbo.json ./
COPY frontend/apps/web/package.json ./apps/web/package.json
COPY frontend/packages/ui/package.json ./packages/ui/package.json
COPY frontend/packages/config/package.json ./packages/config/package.json
RUN --mount=type=cache,target=/root/.bun/install/cache bun install --frozen-lockfile
# …then the sources; turbo builds the app (and its workspace deps) with its task graph.
COPY frontend/ ./
RUN bunx turbo run build --filter=lance-lineage-web

# ── runtime: the node-adapter server only ──────────────────────────────────────
FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04 AS runtime

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION
LABEL org.opencontainers.image.title="lance-lineage-web" \
      org.opencontainers.image.description="Lance lineage UI — SvelteKit (Svelte Flow) graph explorer" \
      org.opencontainers.image.source="https://github.com/Borg93/lance-ns" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV NODE_ENV=production \
    PORT=3000
# NOTE: bun's isolated linker (the workspace default) puts the real packages in the root
# node_modules/.bun store and gives each workspace its own node_modules of symlinks into it
# (../../../../node_modules/.bun/<pkg>@<ver>/…). The SSR server resolves @sveltejs/kit — a devDependency
# svelte-adapter-bun externalizes into build/server but omits from build/package.json — through
# apps/web/node_modules, so the runtime must replicate the whole topology at the same depths: store,
# app symlink farm, and packages/ (workspace symlink targets). Copying only the root node_modules
# breaks resolution ("Cannot find module @sveltejs/kit" — hit live 2026-07-13); a `--production`
# reinstall drops the dev-dep entirely. Full-tree copy is the accepted hygiene cost.
COPY --from=build --link /app/node_modules /app/node_modules
COPY --from=build --link /app/packages /app/packages
COPY --from=build --link /app/apps/web/node_modules /app/apps/web/node_modules
COPY --from=build --link /app/apps/web/build /app/apps/web/build
COPY --from=build --link /app/apps/web/package.json /app/apps/web/package.json
WORKDIR /app/apps/web
EXPOSE 3000
# Bun is the init/PID1 here; the slim image has no curl, so health-check via bun's fetch.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD bun -e "fetch('http://localhost:'+ (process.env.PORT||3000)).then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
# NUMERIC USER (the base image's `bun` account is uid 1000) — k8s `runAsNonRoot: true` can only VERIFY
# non-root at admission when the image user is numeric; a name ("bun") makes the kubelet reject the pod.
USER 1000
ENTRYPOINT ["bun", "./build/index.js"]
