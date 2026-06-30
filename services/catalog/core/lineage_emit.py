"""Best-effort OpenLineage emission from the catalog to the lineage service.

The catalog is the only component that knows the *verified* principal on every write, so it is
the authoritative source of "who created/changed a table". On a table create it emits an
OpenLineage ``RunEvent`` (output = the table, ``author`` = the token sub, plus a ``lance`` run
facet naming the operation + version) to the lineage service's ingest endpoint.

Emission is **fire-and-forget + best-effort**: it runs in a FastAPI background task (after the
response) and swallows every error, so the lineage service being down/slow can never block or
fail a catalog write. Two transports sit behind the same :class:`LineageEmitter` interface:

* :class:`HttpLineageEmitter` — direct HTTP POST (the OpenLineage default transport; simple, but the
  event is lost if the lineage service is down when we POST). Good for dev / external producers.
* :class:`DaprEmitter` — publish to the **Dapr** ``pubsub.jetstream`` component (the production
  transport, ``LANCE_LINEAGE_TRANSPORT=dapr``). We publish to our local Dapr sidecar; the sidecar
  persists to NATS JetStream and owns retry/backoff/DLQ/trace-propagation as **component config** (no
  broker client in app code) — the decoupled microservice path. The lineage service subscribes via its
  own sidecar. The outbox gap (crash between the Lance write and publish) remains: the catalog has no
  DB for a transactional outbox; the durable producer is the Ray job (future), per microservices.md.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

import httpx
from dapr.aio.clients import DaprClient

log = logging.getLogger(__name__)

#: Operation markers carried in the OpenLineage ``lance`` run facet. The lineage service keys the
#: ``(:User)-[:CREATED]->(:Dataset)`` edge off ``create_table`` specifically, so the two sides share
#: these contract strings (see ``lineage/repository.py``); the rest just record a versioned ``WROTE``.
CREATE_TABLE = "create_table"
INSERT = "insert"
MERGE_INSERT = "merge_insert"
UPDATE = "update"
DELETE = "delete"

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

#: OpenLineage standard ``DatasourceDatasetFacet`` schema URL. The output dataset carries this facet with
#: the **physical storage URI** so the lineage service can find the real Lance file on object storage and
#: cross-check the on-disk version (#23 reconcile — ``lineage.models.Dataset.source_uri`` reads
#: ``facets.dataSource.uri``). Without it, reconcile has no URI to read → every real table looks
#: ``missing_on_storage`` (the moat was broken).
_DATASOURCE_FACET_SCHEMA = (
    "https://openlineage.io/spec/facets/1-0-0/DatasourceDatasetFacet.json#/$defs/DatasourceDatasetFacet"
)


def build_write_event(
    *,
    table_id: str,
    namespace: str,
    author: str | None,
    version: int | None,
    operation: str,
    run_id: str,
    event_time: str,
    job_namespace: str,
    source_uri: str | None = None,
) -> dict[str, Any]:
    """Build the OpenLineage ``RunEvent`` (wire JSON) for any catalog write to a table.

    ``table_id`` is the catalog's canonical id (e.g. ``alpha$bronze$images``) so the lineage
    ``Dataset`` name matches the OpenFGA object id byte-for-byte — one identity across the three
    governance axes. ``operation`` is the catalog op (``create_table`` / ``insert`` / ``merge_insert``
    / ``update`` / ``delete``). ``version`` is the Lance version the write produced; when it is ``None``
    (e.g. an insert whose response carries no version) the standard version facet is omitted so the
    ``WROTE`` edge records the run without asserting a version. ``run_id`` / ``event_time`` are injected
    so the builder is pure and deterministically testable.
    """
    lance_facet: dict[str, Any] = {"operation": operation}
    if version is not None:
        lance_facet["version"] = version
    run_facets: dict[str, Any] = {"lance": lance_facet}
    if author is not None:
        run_facets["author"] = {"name": author, "sub": author}
    output: dict[str, Any] = {"namespace": namespace, "name": table_id}
    facets: dict[str, Any] = {}
    if version is not None:
        # Standard version facet → the lineage WROTE edge carries the Lance version (#20).
        facets["version"] = {
            "_producer": _PRODUCER,
            "_schemaURL": _VERSION_FACET_SCHEMA,
            "datasetVersion": str(version),
        }
    if source_uri:
        # Standard dataSource facet → the physical Lance URI, so #23 reconcile can read the on-disk file.
        facets["dataSource"] = {
            "_producer": _PRODUCER,
            "_schemaURL": _DATASOURCE_FACET_SCHEMA,
            "name": source_uri,
            "uri": source_uri,
        }
    if facets:
        output["facets"] = facets
    return {
        "eventType": "COMPLETE",
        "eventTime": event_time,
        "producer": _PRODUCER,
        "run": {"runId": run_id, "facets": run_facets},
        "job": {"namespace": job_namespace, "name": operation},
        "inputs": [],
        "outputs": [output],
    }


def build_create_event(
    *,
    table_id: str,
    namespace: str,
    author: str | None,
    version: int,
    run_id: str,
    event_time: str,
    job_namespace: str,
    source_uri: str | None = None,
) -> dict[str, Any]:
    """The ``RunEvent`` for a table creation — :func:`build_write_event` with ``operation=create_table``."""
    return build_write_event(
        table_id=table_id,
        namespace=namespace,
        author=author,
        version=version,
        operation=CREATE_TABLE,
        run_id=run_id,
        event_time=event_time,
        job_namespace=job_namespace,
        source_uri=source_uri,
    )


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
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
    ) -> None: ...

    async def emit_write(
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int | None,
        operation: str,
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
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
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
    ) -> None:
        return None

    async def emit_write(  # noqa: ARG002
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int | None,
        operation: str,
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
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
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
    ) -> None:
        await self.emit_write(
            table_id=table_id,
            namespace=namespace,
            author=author,
            version=version,
            operation=CREATE_TABLE,
            run_id=run_id,
            authorization=authorization,
            source_uri=source_uri,
        )

    async def emit_write(
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int | None,
        operation: str,
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
    ) -> None:
        event = build_write_event(
            table_id=table_id,
            namespace=namespace,
            author=author,
            version=version,
            operation=operation,
            # For a create this is the run id stamped into the Lance file (#21); for other writes a
            # fresh id. Generate one only when the caller didn't supply it.
            run_id=run_id or str(uuid.uuid4()),
            event_time=datetime.now(UTC).isoformat(),
            job_namespace=self._job_namespace,
            source_uri=source_uri,
        )
        # Forward the caller's bearer so ingest accepts the event when the lineage service has OIDC
        # on (else the event 401s and is silently dropped). The lineage side then binds the author to
        # this same verified principal.
        headers = {"Authorization": authorization} if authorization else None
        try:
            response = await self._client.post(self._url, json=event, headers=headers)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 — best-effort: lineage must never break a catalog write
            log.warning(
                "lineage_emit_failed",
                extra={"operation": operation, "table": table_id, "error": str(exc)},
            )


class DaprEmitter:
    """Publishes OpenLineage events to a **Dapr** ``pubsub.jetstream`` component.

    We publish to the local Dapr **sidecar** (``DaprClient.publish_event``); the sidecar persists to NATS
    JetStream and owns retry/backoff/DLQ + W3C trace-context propagation as *component config*, so the
    app holds no broker client (the decoupled microservice path — microservices.md). The topic is
    versioned (``lineage.events.v1``). Publish stays best-effort: a sidecar/broker outage logs + drops
    rather than failing the catalog write. ``authorization`` is unused — the pub/sub topic is an internal
    catalog-only channel, so the subscriber trusts the verified ``author`` the catalog stamped (the
    anti-forgery ``enforce_author`` guard is only for the open HTTP endpoint).
    """

    def __init__(self, client: DaprClient, pubsub: str, topic: str, *, job_namespace: str) -> None:
        self._client = client
        self._pubsub = pubsub
        self._topic = topic
        self._job_namespace = job_namespace

    async def emit_create(
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int,
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
    ) -> None:
        await self.emit_write(
            table_id=table_id,
            namespace=namespace,
            author=author,
            version=version,
            operation=CREATE_TABLE,
            run_id=run_id,
            authorization=authorization,
            source_uri=source_uri,
        )

    async def emit_write(  # noqa: ARG002 — authorization is unused on the trusted internal channel
        self,
        *,
        table_id: str,
        namespace: str,
        author: str | None,
        version: int | None,
        operation: str,
        run_id: str | None = None,
        authorization: str | None = None,
        source_uri: str | None = None,
    ) -> None:
        event = build_write_event(
            table_id=table_id,
            namespace=namespace,
            author=author,
            version=version,
            operation=operation,
            run_id=run_id or str(uuid.uuid4()),
            event_time=datetime.now(UTC).isoformat(),
            job_namespace=self._job_namespace,
            source_uri=source_uri,
        )
        try:
            await self._client.publish_event(
                pubsub_name=self._pubsub,
                topic_name=self._topic,
                data=json.dumps(event),
                data_content_type="application/json",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort: lineage must never break a catalog write
            log.warning(
                "lineage_publish_failed",
                extra={"operation": operation, "table": table_id, "error": str(exc)},
            )


def make_emitter(
    *,
    enabled: bool,
    transport: str,
    url: str | None,
    client: httpx.AsyncClient | None,
    dapr: DaprClient | None,
    pubsub: str,
    topic: str,
    job_namespace: str,
) -> LineageEmitter:
    """Select the lineage transport: ``dapr`` (durable pub/sub via the sidecar) or ``http`` (direct POST);
    no-op when disabled or unwired (a half-configured transport must never silently become the other)."""
    if not enabled:
        return NoopEmitter()
    if transport == "dapr" and dapr is not None:
        return DaprEmitter(dapr, pubsub, topic, job_namespace=job_namespace)
    if transport == "http" and url and client is not None:
        return HttpLineageEmitter(client, url, job_namespace=job_namespace)
    return NoopEmitter()
