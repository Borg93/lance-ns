"""The mover's stage-transform business logic — one DAG edge, infra-free + testable.

:func:`handle_stage` is the heart of a medallion mover: given one upstream stage trigger it emits the
transform's OpenLineage event (``inputs=[from_dataset]`` -> ``outputs=[to_dataset]`` — the ``DERIVED_FROM``
edge) and publishes the next stage's trigger, so a single producer event cascades raw->bronze->silver->gold.

Idempotent + best-effort: with ``compute_enabled`` the transform does a REAL in-process Lance write (the
fake-Ray compute) and the emit carries the real version; off, it's a pure lineage emit (version 1). The
graph MERGEs on run_id, and a compute/publish outage returns ``RETRY`` so the Dapr sidecar redelivers.
When the FGA gate is on, the mover
CHECKS it is authorized to produce the target stage as its own service identity before emitting — an
unauthorized mover returns ``DROP`` (redelivery won't grant the role), so the cascade enforces the ReBAC.
"""

from __future__ import annotations

import json
import logging
from contextlib import suppress
from typing import Any

from common import fga
from dapr.aio.clients import DaprClient
from fastapi.concurrency import run_in_threadpool
from lance_namespace import ServiceUnavailableError
from openfga_sdk import OpenFgaClient
from opentelemetry import trace

from medallion.core.config import MedallionSettings
from medallion.core.metrics import record_denied, record_quality_blocked, record_transition
from medallion.schemas.events import build_run_event
from medallion.services.compute import transform_stage
from medallion.services.quality import Assertion, assert_quality, passed

log = logging.getLogger(__name__)
# The Lance/S3 write runs in a threadpool and is invisible to every auto-instrumentor — a manual INTERNAL
# span makes the step that dominates wall-clock time visible inside the cascade's distributed trace.
tracer = trace.get_tracer(__name__)

_SUCCESS = {"status": "SUCCESS"}
_RETRY = {"status": "RETRY"}
_DROP = {"status": "DROP"}
# A quality-blocked run was handled (its failed assertions are recorded in lineage), it just must not
# promote — DROP so Dapr doesn't redeliver (the data is deterministically bad; no DLQ is configured,
# so the drop is final — the failed run in the lineage graph is the audit trail).
_QUALITY_BLOCKED = {"status": "DROP"}


async def handle_stage(
    dapr: DaprClient, settings: MedallionSettings, event: Any, *, fga_client: OpenFgaClient | None = None
) -> dict[str, str]:
    """Handle one upstream stage trigger: emit the transform's lineage, then trigger the next stage.
    ``event`` is the untrusted Dapr CloudEvent envelope (hence ``Any`` + the ``isinstance`` guard).

    When ``fga_client`` is set (MEDALLION_FGA_ENABLED), the mover first CHECKS it is authorized to produce
    the target stage — ``can_promote`` for the silver->gold mover, ``can_create_table`` for the others — as
    its own service identity. Unauthorized -> ``DROP`` (redelivery won't grant the role): the cascade
    enforces the ReBAC, so a mover lacking the validator role genuinely cannot promote to gold."""
    data = event.get("data") if isinstance(event, dict) else None
    token = data.get("token") if isinstance(data, dict) else None
    transition = f"{settings.from_namespace}->{settings.to_namespace}"

    if fga_client is not None:
        try:
            allowed = await fga.check(
                fga_client,
                user=settings.fga_service_identity,
                relation=settings.fga_required_action,
                obj=settings.fga_object(),
            )
        except ServiceUnavailableError as exc:
            # An FGA OUTAGE is transient (unlike a denial): return the explicit RETRY contract so the
            # sidecar redelivers, instead of leaking a 500 that is only incidentally retriable.
            log.warning(
                "medallion_stage_fga_unavailable",
                extra={"transition": transition, "token": token, "error": str(exc)},
            )
            return _RETRY
        if not allowed:
            record_denied(transition)
            log.warning(
                "medallion_stage_denied",
                extra={
                    "transition": transition,
                    "identity": settings.fga_service_identity,
                    "action": settings.fga_required_action,
                    "object": settings.fga_object(),
                },
            )
            return _DROP

    quality_blocked = False
    completed = False  # set once the COMPLETE lineage emit lands — gates the FAIL-on-failure below
    try:
        # 0. Fake-Ray compute (opt-in): a REAL in-process Lance write of the downstream dataset, so the
        # emitted lineage carries the actual version + measured output statistics (rows + on-disk bytes),
        # and the cascade produces data, not just provenance. Blocking Lance/S3 IO → threadpool. Off →
        # version 1, no stats (dummy emit). A compute failure → RETRY below. With the quality gate on, the
        # mover then ASSERTS quality on the dataset it just wrote (the produced data is what's validated).
        result = None
        assertions: list[Assertion] = []
        if settings.compute_enabled and settings.from_uri and settings.to_uri:
            with tracer.start_as_current_span("medallion.transform") as span:
                span.set_attribute("lance.medallion.transition", transition)
                result = await run_in_threadpool(
                    transform_stage,
                    settings.from_uri,
                    settings.to_uri,
                    settings.storage_options(),
                    stage=settings.to_namespace,
                )
                span.set_attribute("lance.version", result.version)
                span.set_attribute("lance.row_count", result.row_count)
                span.set_attribute("lance.size_bytes", result.size_bytes)
            if settings.quality_enabled:
                assertions = await run_in_threadpool(
                    assert_quality,
                    settings.to_uri,
                    settings.storage_options(),
                    key_column=settings.quality_key_column,
                )
        run_event = build_run_event(
            operation=settings.operation,
            author=settings.author,
            job_namespace=settings.job_namespace,
            inputs=[(settings.from_namespace, settings.from_dataset)],
            output_namespace=settings.to_namespace,
            output_name=settings.to_dataset,
            version=result.version if result else 1,
            row_count=result.row_count if result else None,
            size_bytes=result.size_bytes if result else None,
            source_uri=settings.to_uri if result else None,
            schema_fields=result.fields if result else None,
            # exclude_none: an assertion with no column omits the key entirely — a serialized
            # ``"column": null`` fails strict DataQualityAssertionsDatasetFacet validation (column: string).
            assertions=[a.model_dump(exclude_none=True) for a in assertions] or None,
            token=token,
        )
        # 1. Emit the transform's lineage (-> the lineage service ingests the DERIVED_FROM edge). This runs
        # even on a quality failure, so the failed assertions are recorded and the bad batch is auditable.
        await dapr.publish_event(
            pubsub_name=settings.pubsub,
            topic_name=settings.lineage_topic,
            data=json.dumps(run_event),
            data_content_type="application/json",
        )
        completed = True  # the COMPLETE is recorded — a later trigger-publish failure is NOT a run failure
        # 2. Quality gate: a failed assertion BLOCKS promotion — record it, but do NOT trigger the next
        # stage, so a bad batch can't cascade. Composes with the FGA gate above (authz AND data-quality).
        if assertions and not passed(assertions):
            quality_blocked = True
        # 3. Trigger the next stage (unless terminal — gold has no pub_topic — or blocked by the gate).
        elif settings.pub_topic:
            await dapr.publish_event(
                pubsub_name=settings.pubsub,
                topic_name=settings.pub_topic,
                data=json.dumps(
                    {"token": token, "dataset": settings.to_dataset, "namespace": settings.to_namespace}
                ),
                data_content_type="application/json",
            )
    except Exception as exc:  # noqa: BLE001 — transient compute/publish failure → let Dapr redeliver
        log.warning(
            "medallion_stage_failed", extra={"transition": transition, "token": token, "error": str(exc)}
        )
        # Record the failed run ONLY if the transform itself failed — i.e. the COMPLETE was never emitted.
        # A failure AFTER the COMPLETE (the downstream trigger publish) is NOT a run failure: the run
        # succeeded and its COMPLETE is already recorded; emitting a FAIL then would flip that successful
        # run to FAIL (and leave a spurious FAIL feed row). Such a case just RETRIES — redelivery re-emits
        # the idempotent COMPLETE + re-publishes the trigger. The FAIL RunEvent keeps a bare output (WROTE
        # edge, no version) + the errorMessage facet; best-effort + suppressed so it can't mask the RETRY;
        # idempotent on the deterministic run_id.
        if not completed:
            with suppress(Exception):
                fail_event = build_run_event(
                    operation=settings.operation,
                    author=settings.author,
                    job_namespace=settings.job_namespace,
                    inputs=[(settings.from_namespace, settings.from_dataset)],
                    output_namespace=settings.to_namespace,
                    output_name=settings.to_dataset,
                    token=token,
                    event_type="FAIL",
                    error_message=str(exc),
                )
                await dapr.publish_event(
                    pubsub_name=settings.pubsub,
                    topic_name=settings.lineage_topic,
                    data=json.dumps(fail_event),
                    data_content_type="application/json",
                )
        return _RETRY
    if quality_blocked:
        record_quality_blocked(transition)
        log.warning(
            "medallion_quality_blocked",
            extra={"transition": transition, "token": token, "to": settings.to_dataset},
        )
        return _QUALITY_BLOCKED
    record_transition(transition)
    log.info(
        "medallion_stage_moved", extra={"transition": transition, "token": token, "to": settings.to_dataset}
    )
    return _SUCCESS
