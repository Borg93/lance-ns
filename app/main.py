"""Lance Namespace REST Catalog — FastAPI application entry.

A Python/FastAPI adapter exposing the full Lance Namespace REST API (spec.yaml)
over a native ``lance.namespace`` backend (``DirectoryNamespace`` on MinIO/S3 by
default), with the pylance data plane filling operations the backend stubs.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from lance_namespace import LanceNamespaceError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import problem_detail
from app.core.namespace import build_namespace
from app.core.oidc import OIDCVerifier

log = logging.getLogger(__name__)

PROBLEM_JSON = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.shutting_down = False
    app.state.startup_complete = False
    app.state.namespace = build_namespace(settings)  # fail fast if storage misconfigured
    if settings.oidc_enabled and settings.oidc_issuer and settings.oidc_audience:
        app.state.oidc = OIDCVerifier(settings.oidc_issuer, settings.oidc_audience, settings.oidc_cache_ttl)
    app.state.startup_complete = True
    try:
        yield
    finally:
        app.state.shutting_down = True


_settings = get_settings()
app = FastAPI(
    title="Lance Namespace REST Catalog",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if _settings.docs_enabled else None,
    openapi_url="/openapi.json" if _settings.docs_enabled else None,
)
app.include_router(api_router)


@app.exception_handler(LanceNamespaceError)
async def handle_domain_error(request: Request, exc: LanceNamespaceError) -> JSONResponse:
    status, body = problem_detail(exc)
    if status >= 500:
        log.exception("domain error on %s %s", request.method, request.url.path)
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
    log.exception("unhandled error on %s %s", request.method, request.url.path)
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
