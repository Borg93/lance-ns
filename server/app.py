"""Lance Namespace REST Catalog — FastAPI application.

A thin, Python/FastAPI adapter that exposes the full Lance Namespace REST API
(spec.yaml) over a native ``lance.namespace`` backend (``DirectoryNamespace`` on
MinIO/S3 by default). Operations are implemented by the native Rust namespace;
this app handles routing, (de)serialization, error mapping, and health.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lance_namespace import ErrorCode, LanceNamespaceError

from server.common import STATUS
from server.factory import build_namespace
from server.routes import router
from server.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.namespace = build_namespace(
        settings
    )  # fail fast if storage is misconfigured
    app.state.ready = True
    try:
        yield
    finally:
        app.state.ready = False


settings = get_settings()
app = FastAPI(
    title="Lance Namespace REST Catalog",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)
app.include_router(router)


@app.exception_handler(LanceNamespaceError)
async def _lance_error(request: Request, exc: LanceNamespaceError) -> JSONResponse:
    return JSONResponse(
        status_code=STATUS.get(int(exc.code), 500),
        content={"error": str(exc), "code": int(exc.code)},
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "code": int(ErrorCode.INTERNAL)},
    )


@app.get("/health")
@app.get("/livez")
def livez() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    ready = getattr(request.app.state, "ready", False)
    ns = getattr(request.app.state, "namespace", None)
    body = {"status": "ready" if ready else "not_ready"}
    if ns is not None:
        try:
            body["namespace"] = ns.namespace_id()
        except Exception:
            pass
    return JSONResponse(status_code=200 if ready else 503, content=body)
