"""OpenLineage HTTP ingest endpoint (``POST /api/v1/lineage``) for external producers.

The OpenLineage HTTP-transport default path: any producer (our emitter, Airflow, Spark, dbt, …)
configured with ``OPENLINEAGE_URL`` pointed here ingests with no glue — the lightweight-Marquez
contract. Durable catalog→lineage delivery rides the Dapr subscription (``lineage.api.dapr``) instead.
"""

from __future__ import annotations

from fastapi import APIRouter

from lineage.api.dependencies import RepositoryDep
from lineage.api.fga_deps import enforce_author
from lineage.api.security import CurrentToken
from lineage.models import RunEvent
from lineage.services.consumer import record_event_best_effort

router = APIRouter(prefix="/api/v1", tags=["ingest"])


@router.post("/lineage", status_code=201)
async def ingest_event(event: RunEvent, repository: RepositoryDep, token: CurrentToken) -> dict[str, str]:
    """Ingest one OpenLineage ``RunEvent`` into the lineage graph.

    This is the OpenLineage HTTP-transport default path, so any OpenLineage producer
    (our emitter, Airflow, Spark, dbt, …) configured with ``OPENLINEAGE_URL`` pointed
    here ingests with no glue — the lightweight-Marquez contract.

    When OIDC is enabled the ``CurrentToken`` dependency requires a verified bearer token
    (401 otherwise) and :func:`~lineage.api.fga_deps.enforce_author` binds the run author to that
    token's subject — a producer cannot self-assert someone else's identity.
    """
    enforce_author(event, token)
    await repository.ingest_event(event)
    # The durable events feed is a secondary projection of the authoritative AGE graph (committed above);
    # the feed write is best-effort and shared with the JetStream consumer so both paths project alike.
    await record_event_best_effort(repository, event)
    return {"status": "ingested", "run": event.run.run_id}
