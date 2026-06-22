# syntax=docker/dockerfile:1.11
# Lance Namespace REST Catalog — production image.
# Build context = repo root:  docker build -f .docker/rest-catalog.dockerfile .

# ── builder ──────────────────────────────────────────────────────────────────
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim@sha256:7820aa74c8a3147ab13553c127432656969548971fbe350ba46a975b59dd42b2 AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app

# Install only third-party deps from the lockfile (no project source yet → cached
# until pyproject.toml / uv.lock change). This project is a virtual app, so
# --no-install-project leaves just the dependency graph in /opt/venv.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# ── final ────────────────────────────────────────────────────────────────────
FROM python:3.13-slim-trixie@sha256:c33f0bc4364a6881bed1ec0cc2665e6c53c87a43e774aaeab88e6f17af105e4f AS final

ARG BUILD_DATE
ARG VCS_REF
ARG VERSION
LABEL org.opencontainers.image.title="lance-rest-catalog" \
      org.opencontainers.image.description="Lance Namespace REST Catalog (FastAPI over native DirectoryNamespace, MinIO/S3)" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"

# tini for correct PID 1 signal handling / zombie reaping.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=builder --link /opt/venv /opt/venv
COPY --link server ./server

USER app
EXPOSE 2333

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:2333/livez').read()"]

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "2333"]
