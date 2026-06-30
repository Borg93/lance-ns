"""Lance Namespace REST Catalog — FastAPI application entry.

A Python/FastAPI adapter exposing the full Lance Namespace REST API (spec.yaml)
over a native ``lance.namespace`` backend (``DirectoryNamespace`` on MinIO/S3 by
default), with the pylance data plane filling operations the backend stubs.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

import httpx
from common import fga
from common.exceptions import problem_detail
from common.oidc import OIDCVerifier
from common.secrets import fetch_dapr_secret
from dapr.aio.clients import DaprClient
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from lance_namespace import LanceNamespaceError
from pydantic import SecretStr

from catalog.api.maintenance import maintenance_middleware
from catalog.api.v1.router import api_router
from catalog.core.config import get_settings
from catalog.core.lineage_emit import make_emitter
from catalog.core.namespace import build_namespace

log = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.shutting_down = False
    app.state.startup_complete = False
    # Consume the sensitive S3 secret from the Dapr secret store (OpenBao) — the store is the SOLE source
    # of truth, NOT a fallback (the audit's 'wired but never read' / 'plaintext still ships' fix). With
    # secrets_from_dapr on, the chart does not put the secret in pod env, so reading the env would yield
    # nothing — we fetch from the store (retrying while it seeds) and FAIL CLOSED if it never arrives,
    # rather than booting with an empty/plaintext key.
    if settings.secrets_from_dapr:
        # Strict sole source: a store miss FAILS CLOSED — never fall back to a plaintext env value (the
        # chart ships none when openbao is on, and silently using one would contradict 'OpenBao is the
        # sole source'). fetch_dapr_secret retries while the store/sidecar/seed come up.
        bundle = fetch_dapr_secret(settings.dapr_secret_store, settings.dapr_secret_key)
        s3_secret = bundle.get(settings.dapr_secret_s3_field)
        if not s3_secret:
            raise RuntimeError(
                f"S3 secret unavailable from Dapr store {settings.dapr_secret_store!r}/"
                f"{settings.dapr_secret_key!r} — failing closed (store is the sole source)"
            )
        settings.s3_secret_access_key = SecretStr(s3_secret)
        log.info("secret_from_dapr_store", extra={"field": settings.dapr_secret_s3_field})
    elif not settings.s3_secret_access_key.get_secret_value():
        raise RuntimeError("LANCE_S3_SECRET_ACCESS_KEY is required when secrets_from_dapr is off")
    app.state.namespace = build_namespace(settings)  # fail fast if storage misconfigured
    if settings.oidc_enabled and settings.oidc_issuer and settings.oidc_audience:
        app.state.oidc = OIDCVerifier(
            settings.oidc_issuer,
            settings.oidc_audience,
            settings.oidc_cache_ttl,
            leeway=settings.oidc_leeway,
            allow_insecure=settings.oidc_allow_insecure,
        )
    if settings.fga_enabled:
        store_id, model_id = settings.fga_store_id, settings.fga_model_id
        if not (store_id and model_id):
            store_id, model_id = await fga.provision(settings.fga_api_url)
            log.info("openfga_provisioned", extra={"store_id": store_id, "model_id": model_id})
        app.state.fga = fga.make_client(
            settings.fga_api_url, store_id, model_id, timeout_seconds=settings.fga_timeout_seconds
        )
    # Lineage emission (opt-in, best-effort). Build the chosen transport: a Dapr pub/sub publisher (the
    # sidecar persists to NATS) or a direct-HTTP client. The Dapr client targets the local sidecar, so
    # it's cheap to construct and needs no broker reachability at boot.
    lineage_http = None
    dapr_client = None
    if settings.lineage_emit_enabled and settings.lineage_transport == "dapr":
        dapr_client = DaprClient()
    elif settings.lineage_emit_enabled and settings.lineage_url:
        lineage_http = httpx.AsyncClient(timeout=settings.lineage_emit_timeout_seconds)
    app.state.lineage_http = lineage_http
    app.state.lineage_dapr = dapr_client
    app.state.lineage_emitter = make_emitter(
        enabled=settings.lineage_emit_enabled,
        transport=settings.lineage_transport,
        url=settings.lineage_url,
        client=lineage_http,
        dapr=dapr_client,
        pubsub=settings.dapr_pubsub,
        topic=settings.dapr_topic,
        job_namespace=settings.lineage_job_namespace,
    )
    app.state.startup_complete = True
    try:
        yield
    finally:
        app.state.shutting_down = True
        fga_client = getattr(app.state, "fga", None)
        # Each close is isolated so one failing teardown can't strand the other resource.
        if fga_client is not None:
            with suppress(Exception):
                await fga_client.close()
        if lineage_http is not None:
            with suppress(Exception):
                await lineage_http.aclose()
        if dapr_client is not None:
            with suppress(Exception):
                await dapr_client.close()


_settings = get_settings()
app = FastAPI(
    title="Lance Namespace REST Catalog",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _settings.docs_enabled else None,
    openapi_url="/openapi.json" if _settings.docs_enabled else None,
)
app.include_router(api_router)
# Read-only maintenance gate (no-op unless LANCE_MAINTENANCE_READ_ONLY=true).
app.middleware("http")(maintenance_middleware)


@app.exception_handler(LanceNamespaceError)
async def handle_domain_error(request: Request, exc: LanceNamespaceError) -> JSONResponse:
    status, body = problem_detail(exc)
    if status >= 500:
        log.exception(
            "domain_error", extra={"method": request.method, "path": request.url.path, "status": status}
        )
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "type": "https://lance.org/problems/validation",
            "title": "Validation Error",
            "status": 422,
            "errors": [
                {"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"], "type": e["type"]}
                for e in exc.errors()
            ],
        },
        media_type=PROBLEM_JSON,
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Internals (native/Arrow/S3 error text, paths) leak via logs only — never the body.
    log.exception("unhandled_error", extra={"method": request.method, "path": request.url.path})
    return JSONResponse(
        status_code=500,
        content={
            "type": "https://lance.org/problems/internal",
            "title": "InternalError",
            "status": 500,
            "detail": "Internal Server Error",
        },
        media_type=PROBLEM_JSON,
    )


@app.get("/livez", tags=["health"])
def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", tags=["health"])
def readyz(request: Request) -> JSONResponse:
    state = request.app.state
    if getattr(state, "shutting_down", False):
        return JSONResponse(status_code=503, content={"status": "shutting_down"})
    if not getattr(state, "startup_complete", False):
        return JSONResponse(status_code=503, content={"status": "starting"})

    body: dict[str, object] = {"status": "ready"}
    ns = getattr(state, "namespace", None)
    if ns is not None:
        with suppress(LanceNamespaceError):
            body["namespace"] = ns.namespace_id()
    return JSONResponse(status_code=200, content=body)
