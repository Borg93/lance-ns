"""Best-effort OpenLineage emission from the catalog to the lineage service.

The catalog is the only component that knows the *verified* principal on every write, so it is
the authoritative source of "who created/changed a table". On a table create it emits an
OpenLineage ``RunEvent`` (output = the table, ``author`` = the token sub, plus a ``lance`` run
facet naming the operation + version) to the lineage service's ingest endpoint.

Emission is **fire-and-forget + best-effort**: it runs in a FastAPI background task (after the
response) and swallows every error, so the lineage service being down/slow can never block or
fail a catalog write. This is the direct-HTTP OpenLineage producer transport; the durable path
(publish to NATS JetStream, lineage consumes) is future work and slots in behind the same
:class:`LineageEmitter` interface.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import httpx

log = logging.getLogger(__name__)

#: Operation marker carried in the OpenLineage ``lance`` run facet. The lineage service keys the
#: ``(:User)-[:CREATED]->(:Dataset)`` edge off this value, so the two sides share this contract
#: string (see ``lineage/repository.py``).
CREATE_TABLE = "create_table"

#: OpenLineage ``producer`` URI — identifies the software that emitted the event (spec-required,
#: and what a Marquez-style consumer records as the event source).
_PRODUCER = "https://github.com/Borg93/lance-ns/tree/main/app/core/lineage_emit.py"

#: OpenLineage standard ``DatasetVersionDatasetFacet`` schema URL. The output dataset carries this
#: facet so the lineage service records the Lance version on the ``WROTE`` edge
#: (``repository.output_version`` reads ``outputs[].facets.version.datasetVersion``) — without it a real
#: ``create_table`` persists a versionless edge (the custom ``lance`` run facet is not read for version).
_VERSION_FACET_SCHEMA = (
    "https://openlineage.io/spec/facets/1-0-1/DatasetVersionDatasetFacet.json"
    "#/$defs/DatasetVersionDatasetFacet"
)


def build_create_event(
    *,
    table_id: str,
    namespace: str,
    author: str | None,
    version: int,
    run_id: str,
    event_time: str,
    job_namespace: str,
) -> dict[str, Any]:
    """Build the OpenLineage ``RunEvent`` (wire JSON) for a table creation.

    ``table_id`` is the catalog's canonical id (e.g. ``alpha$bronze$images``) so the lineage
    ``Dataset`` name matches the OpenFGA object id byte-for-byte — one identity across the three
    governance axes. ``run_id`` / ``event_time`` are injected (not generated here) so the builder
    is pure and deterministically testable.
    """
    run_facets: dict[str, Any] = {"lance": {"operation": CREATE_TABLE, "version": version}}
    if author is not None:
        run_facets["author"] = {"name": author, "sub": author}
    return {
        "eventType": "COMPLETE",
        "eventTime": event_time,
        "producer": _PRODUCER,
        "run": {"runId": run_id, "facets": run_facets},
        "job": {"namespace": job_namespace, "name": CREATE_TABLE},
        "inputs": [],
        "outputs": [
            {
                "namespace": namespace,
                "name": table_id,
                # Standard version facet → the lineage WROTE edge carries the Lance version (#20).
                "facets": {
                    "version": {
                        "_producer": _PRODUCER,
                        "_schemaURL": _VERSION_FACET_SCHEMA,
                        "datasetVersion": str(version),
                    }
                },
            }
        ],
    }


@runtime_checkable
class LineageEmitter(Protocol):
    """Emits catalog write events to the lineage service (best-effort)."""

    async def emit_create(
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int,
        authorization: str | None = None,
    ) -> None: ...


class NoopEmitter:
    """The emitter used when lineage emission is disabled — does nothing."""

    async def emit_create(  # noqa: ARG002
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int,
        authorization: str | None = None,
    ) -> None:
        return None


class HttpLineageEmitter:
    """POSTs OpenLineage events to the lineage service, swallowing every failure."""

    def __init__(self, client: httpx.AsyncClient, url: str, *, job_namespace: str) -> None:
        self._client = client
        self._url = url
        self._job_namespace = job_namespace

    async def emit_create(
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int,
        authorization: str | None = None,
    ) -> None:
        event = build_create_event(
            table_id=table_id,
            namespace=namespace,
            author=author,
            version=version,
            run_id=str(uuid.uuid4()),
            event_time=datetime.now(UTC).isoformat(),
            job_namespace=self._job_namespace,
        )
        # Forward the caller's bearer so ingest accepts the event when the lineage service has OIDC
        # on (else every create event 401s and is silently dropped). The lineage side then binds the
        # author to this same verified principal.
        headers = {"Authorization": authorization} if authorization else None
        try:
            response = await self._client.post(self._url, json=event, headers=headers)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — best-effort: lineage must never break a catalog write
            log.warning(
                "lineage_emit_failed",
                extra={"operation": CREATE_TABLE, "table": table_id, "error": str(exc)},
            )


def make_emitter(
    *, enabled: bool, url: str | None, client: httpx.AsyncClient | None, job_namespace: str
) -> LineageEmitter:
    """Return the HTTP emitter when enabled + wired, else a no-op."""
    if enabled and url and client is not None:
        return HttpLineageEmitter(client, url, job_namespace=job_namespace)
    return NoopEmitter()
