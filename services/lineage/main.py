"""Lineage service — FastAPI app: ingest OpenLineage events, query the graph.

A sibling microservice to the catalog (it owns the AGE graph; nobody else touches
it). Run: ``uvicorn lineage.main:app``. See ``docs/LINEAGE.md``.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from common import fga
from common.dapr_auth import assert_app_token_configured
from common.exceptions import problem_detail
from common.oidc import OIDCVerifier
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from lance_namespace import LanceNamespaceError

from lineage.api.dapr import register_dapr
from lineage.api.v1.endpoints import demo
from lineage.api.v1.router import api_router
from lineage.core.age import make_pool
from lineage.core.config import apply_dapr_secrets, get_settings
from lineage.services.repository import LineageRepository

log = logging.getLogger(__name__)
PROBLEM_JSON = "application/problem+json"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    # Fail closed if Dapr ingest is on but the app-api-token is unset — the ingest route would otherwise be
    # an unauthenticated forgery path (the audit's 'blanked token' residual). No-op in dev (Dapr off).
    assert_app_token_configured(dapr_enabled=settings.dapr_enabled)
    # Consume the S3 secret + AGE DB password from the Dapr secret store (OpenBao) before opening the pool,
    # so neither lives in plaintext pod env — the audit's secret-consumption fix, symmetric with the
    # catalog. No-op (and no Dapr dependency) when secrets_from_dapr is off; fails closed on the S3 secret.
    apply_dapr_secrets(settings)
    pool = make_pool(settings.database_url)
    await pool.open()
    app.state.pool = pool
    repository = LineageRepository(pool, settings.graph, events_retention=settings.events_retention)
    app.state.repository = repository
    # Durable events feed: a Postgres table created on first boot. /runs folds onto the AGE (:Run)
    # node; both now survive restart + are replica-shared — no in-memory state. (#22)
    await repository.ensure_events_table()
    await repository.ensure_reads_table()  # the read-audit log (#6); off unless LINEAGE_READ_AUDIT_ENABLED
    # Auth is opt-in; when enabled, reuse the catalog's verifier + the shared OpenFGA store.
    if settings.oidc_enabled and settings.oidc_issuer and settings.oidc_audience:
        app.state.oidc = OIDCVerifier(
            settings.oidc_issuer,
            settings.oidc_audience,
            settings.oidc_cache_ttl,
            leeway=settings.oidc_leeway,
            allow_insecure=settings.oidc_allow_insecure,
        )
    if settings.fga_enabled:
        # Converge on the catalog's store: provision is idempotent by store NAME ("lance-catalog"), so
        # both services resolve the same store + model without the id being pinned ahead of boot. (The
        # catalog writes the grants on create; lineage reads them — one shared Zanzibar store.)
        store_id, model_id = settings.fga_store_id, settings.fga_model_id
        if not (store_id and model_id):
            store_id, model_id = await fga.provision(settings.fga_api_url)
            log.info("openfga_provisioned", extra={"store_id": store_id, "model_id": model_id})
        app.state.fga = fga.make_client(
            settings.fga_api_url, store_id, model_id, timeout_seconds=settings.fga_timeout_seconds
        )
    # Durable ingest (#25) is the Dapr subscription wired below (declarative — the sidecar drives it);
    # there is no consumer task to manage here. The HTTP /api/v1/lineage path stays for external producers.
    try:
        yield
    finally:
        fga_client = getattr(app.state, "fga", None)
        if fga_client is not None:
            await fga_client.close()
        await pool.close()


app = FastAPI(title="Lance Lineage Service", version="0.1.0", lifespan=lifespan)

# Dapr pub/sub subscription (#25): build app first, then wire the subscription so `app` exists before
# the registration. DaprApp(app) also serves GET /dapr/subscribe (the sidecar's startup registration).
register_dapr(app)
app.include_router(api_router)


@app.exception_handler(LanceNamespaceError)
async def handle_domain_error(request: Request, exc: LanceNamespaceError) -> JSONResponse:
    """Render auth/availability failures (401 / 403 / 503) as RFC 9457 problem+json."""
    status, body = problem_detail(exc)
    if status >= 500:
        log.exception(
            "domain_error",
            extra={"method": request.method, "path": request.url.path, "status": status},
        )
    return JSONResponse(status_code=status, content=body, media_type=PROBLEM_JSON)


@app.get("/livez", tags=["health"])
async def livez() -> dict[str, str]:
    return {"status": "ok"}


# Demo data peek (reads the real Lance datasets on S3) — mounted only when explicitly enabled.
if get_settings().demo_data_enabled:
    app.include_router(demo.router)

# Thin demo UI — a single self-contained page that polls the query endpoints to render the live
# medallion DAG (see scripts/medallion_demo.py). Mounted last so it never shadows an API route.
_STATIC = Path(__file__).resolve().parent / "static"
if _STATIC.is_dir():
    app.mount("/ui", StaticFiles(directory=str(_STATIC), html=True), name="ui")
