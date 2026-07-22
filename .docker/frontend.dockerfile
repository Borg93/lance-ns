# syntax=docker/dockerfile:1.11
# Lance micro-frontend zone image — SvelteKit SSR built with Bun and RUN by the Bun runtime
# (svelte-adapter-bun ships a Bun *server*, not static files). Build context = repo root; the JS
# workspace lives under frontend/. Mirrors rask/.docker/frontend.dockerfile.
#
# Parametrized over the zone via --build-arg APP=<dir under frontend/components/frontends>:
#   docker build -f .docker/frontend.dockerfile --build-arg APP=data \
#     --build-arg BUILD_DATE=$(date -u +%FT%TZ) --build-arg VCS_REF=$(git rev-parse HEAD) \
#     --build-arg VERSION=$(git describe --always) -t lance-data:dev .
# APP=home builds the catch-all (serves "/"); the others build the domain zones
# (data/lineage/models/admin), each pinned to its base path /<zone> in svelte.config.js.
#
# Two bun-1.3 + svelte-adapter-bun gotchas this encodes (same as the old web.dockerfile):
#  1. the adapter externalizes @sveltejs/kit (+ the svelte runtime) → the runtime ships node_modules
#     (build/ is NOT standalone). @rask/ui + @rask/api are BUNDLED into the zone's build/, so packages/
#     is not needed at runtime — only the store + the app's own symlinked node_modules.
#  2. bun 1.3 isolated linker: real packages live in node_modules/.bun/<pkg>; each workspace member's
#     node_modules holds symlinks INTO that store. The final image copies the store (root node_modules)
#     AND the app (with its symlinked node_modules) at the path the relative symlinks expect, then runs
#     from the app dir.

# ---- builder: bun install (workspace) + prebuild @rask/ui + bun build the zone --------------------
FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04 AS builder

ARG APP=home
WORKDIR /src

# Every JS workspace member must be present or `bun install --frozen-lockfile` errors with "Workspace
# not found". Copy the whole workspace (apps + packages + all zones) so a new member can't silently break
# this build; .dockerignore strips node_modules/.svelte-kit/build. patchedDependencies (svelte-adapter-bun)
# are resolved relative to the workspace root, so patches/ must be present for the frozen install.
COPY frontend/package.json frontend/bun.lock frontend/turbo.json ./
COPY frontend/patches patches
COPY frontend/packages packages
COPY frontend/components/frontends components/frontends

RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun install --frozen-lockfile

# Pre-build @rask/ui (svelte-package → dist/) so its dist exports resolve during the zone build; then
# build the requested zone (vite bundles the app + @rask/ui + @rask/api into build/).
# hadolint ignore=DL3059
RUN --mount=type=cache,target=/root/.bun/install/cache \
    bun run --cwd packages/rask-ui build \
    && bun run --cwd components/frontends/${APP} build

# ---- runtime: minimal Bun runtime serving the adapter-bun server ---------------------------------
FROM oven/bun:1.3.14-slim@sha256:d56a2534ffd262e92c12fd3249d3924d296d97086da773f821d7d0477435ea04 AS runtime

ARG APP=home
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION
LABEL org.opencontainers.image.title="lance-${APP}" \
      org.opencontainers.image.description="Lance ${APP} micro-frontend zone (SvelteKit SSR), Bun server" \
      org.opencontainers.image.source="https://github.com/Borg93/lance-ns" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"

# tini as PID 1 (reaps the Bun server's children, forwards signals for a clean rolling-update drain).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends tini

# Numeric non-root uid (>=10000) so k8s runAsNonRoot can VERIFY it at admission (a named user makes the
# kubelet reject the pod). Created without a home/shell — nothing to log into.
RUN useradd -r -u 10001 --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app

# Preserve the isolated-linker layout: the store (root node_modules) + the app with its symlinked
# node_modules at the SAME relative depth the symlinks expect (components/frontends/<app>).
COPY --from=builder --chown=10001:10001 /src/node_modules ./node_modules
COPY --from=builder --chown=10001:10001 /src/components/frontends/${APP} ./components/frontends/${APP}

# Re-anchor the workdir at the app via a stable symlink so CMD is APP-agnostic.
RUN ln -s "components/frontends/${APP}" /app/app
WORKDIR /app/app

USER 10001
ENV NODE_ENV=production \
    PORT=3000 \
    HOST=0.0.0.0 \
    HOME=/tmp
EXPOSE 3000

# Hit "/" and accept any non-5xx: the domain zones have a base path so "/" is 404 (<500), which still
# proves the adapter-bun server is alive without hardcoding each zone's base. The slim image has no curl,
# so probe via bun's fetch.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=5 \
    CMD bun -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))"

ENTRYPOINT ["tini", "--"]
CMD ["bun", "build/index.js"]
