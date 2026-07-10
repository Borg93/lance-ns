"""The Ray TRAIN head + trainer consumer business logic (#115a, docs/RAY-TRAIN.md D1/D2/D5).

``submit_train_request`` (the ``POST /train`` head) resolves every feature's Lance version — an omitted
version pins to LATEST **at the head** (D1: the pin is resolved here and threaded through, never left
floating inside the job) — then publishes the training trigger to the DEDICATED topic. The trigger
carries pointers only (dataset names + versions + a small config), never data (claim-check).

``handle_train_trigger`` (the subscription consumer) FGA-gates as the trainer's OWN identity —
``can_read_data`` on EVERY pinned input and ``can_create_table`` on the models namespace (D5: never the
medallion writer rung) — then SUBMITS the Ray job and acks (D2: submit-and-ack; the job emits its own
OpenLineage lifecycle). Deny → DROP before any compute is spent; FGA outage → RETRY; a terminally
FAILED prior job → DROP (no auto-resubmit of expensive training).
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from common import dapr_publish, fga
from dapr.aio.clients import DaprClient
from fastapi.concurrency import run_in_threadpool
from lance_namespace import ServiceUnavailableError

from medallion.core.config import MedallionSettings
from medallion.services import ray_submit

log = logging.getLogger(__name__)

_SUCCESS = {"status": "SUCCESS"}
_RETRY = {"status": "RETRY"}
_DROP = {"status": "DROP"}

#: Claim-check ceiling for the trigger's config payload (pointers + hyperparams, never data).
_MAX_CONFIG_BYTES = 8192


def train_head_enabled(settings: MedallionSettings) -> bool:
    """The train head needs the Ray path + S3 + a raw URI to derive stage URIs from — 409 otherwise
    (an explicit contract, like the media head; never a KeyError 500)."""
    return bool(settings.ray_enabled and settings.s3_endpoint and settings.raw_uri)


def stage_uri_for(settings: MedallionSettings, dataset: str) -> str:
    """Derive a medallion dataset's URI from its name — ``silver$features`` → ``…/medallion/silver``.

    The cascade lays every stage out as a sibling of the raw dataset (``…/medallion/<stage>``), so the
    stage URI is the raw URI's parent + the dataset's namespace segment. Demo-tier convention — a
    catalog-registered feature table would resolve through describe instead (future #115 work).
    """
    stage = dataset.split("$", 1)[0]
    parent = settings.raw_uri.rstrip("/").rsplit("/", 1)[0]
    return f"{parent}/{stage}"


def _resolve_version(settings: MedallionSettings, dataset: str) -> int:
    """The dataset's CURRENT Lance version (blocking read — call via threadpool)."""
    import lance

    ds = lance.dataset(stage_uri_for(settings, dataset), storage_options=settings.storage_options())
    return int(ds.version)


async def submit_train_request(
    dapr: DaprClient,
    settings: MedallionSettings,
    *,
    model: str,
    features: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve feature-version pins and publish the training trigger; returns ``{token, features}``.

    A resolution failure (unknown dataset / unreadable storage) surfaces as ``resolve_failed`` and a
    publish failure as ``publish_failed`` — the route maps both to explicit errors rather than a 202
    that silently trains against nothing.
    """
    token = uuid.uuid4().hex[:12]
    # Claim-check guard: the trigger carries pointers + a SMALL config — never data-shaped content
    # (NATS messages must stay small JSON; an inlined matrix would degrade the broker for everyone).
    if len(json.dumps(config or {})) > _MAX_CONFIG_BYTES:
        return {"status": "config_too_large"}
    pinned: list[dict[str, Any]] = []
    for feature in features:
        dataset = feature["dataset"]
        version = feature.get("version")
        if version is None:
            try:
                version = await run_in_threadpool(_resolve_version, settings, dataset)
            except Exception as exc:  # noqa: BLE001 — surface, don't 500: the caller named the dataset
                log.warning("train_resolve_failed", extra={"dataset": dataset, "error": str(exc)})
                return {"status": "resolve_failed", "dataset": dataset}
        pinned.append({"dataset": dataset, "version": int(version)})
    payload = {"token": token, "model": model, "features": pinned, "config": config or {}}
    try:
        await dapr_publish.publish_event(
            dapr,
            timeout_seconds=settings.publish_timeout_seconds,
            pubsub_name=settings.pubsub,
            topic_name=settings.train_topic,
            data=json.dumps(payload),
            data_content_type="application/json",
        )
    except Exception as exc:  # noqa: BLE001 — the head must surface a lost trigger, not hide it in a 202
        log.warning("train_publish_failed", extra={"token": token, "error": str(exc)})
        return {"status": "publish_failed", "token": token}
    log.info("train_requested", extra={"token": token, "model": model, "features": pinned})
    return {"token": token, "model": model, "features": pinned}


async def handle_train_trigger(
    settings: MedallionSettings, event: Any, *, fga_client: Any | None = None
) -> dict[str, str]:
    """Consume one training trigger: gate, submit-and-ack (D2) — never block on job completion.

    ``event`` is the untrusted Dapr CloudEvent envelope. Malformed → DROP (redelivery can't fix a bad
    payload). With FGA on: ``can_read_data`` on every input + ``can_create_table`` on the models
    namespace as the TRAINER identity; deny → DROP (attributable — redelivery won't grant the rung),
    outage → RETRY. A transport/submit failure → RETRY (the deterministic id re-attaches); a prior
    terminally-FAILED job → DROP (D2: no auto-resubmit of expensive training).
    """
    data = event.get("data") if isinstance(event, dict) else None
    if not isinstance(data, dict) or not data.get("token") or not data.get("model"):
        log.warning("train_trigger_malformed", extra={"event": str(event)[:200]})
        return _DROP
    token, model = data["token"], data["model"]
    # STRICT feature validation (review 2026-07-10): every entry needs a dataset AND an int version —
    # a version-less feature would train on floating LATEST (violates D1 + #115b's guardrail), and an
    # empty/malformed list would pass the per-input gate VACUOUSLY. Either way: DROP, not repair.
    raw_features = data.get("features") or []
    features = [
        f
        for f in raw_features
        if isinstance(f, dict) and f.get("dataset") and isinstance(f.get("version"), int)
    ]
    if not features or len(features) != len(raw_features):
        log.warning("train_trigger_malformed", extra={"token": token, "features": str(raw_features)[:200]})
        return _DROP

    if fga_client is not None:
        try:
            for feature in features:
                if not await fga.check(
                    fga_client,
                    user=settings.trainer_identity,
                    relation="can_read_data",
                    obj=f"table:{feature['dataset']}",
                ):
                    log.warning("train_denied", extra={"token": token, "input": feature["dataset"]})
                    return _DROP
            if not await fga.check(
                fga_client,
                user=settings.trainer_identity,
                relation="can_create_table",
                obj=f"namespace:{settings.models_namespace}",
            ):
                log.warning("train_denied", extra={"token": token, "input": "models namespace"})
                return _DROP
        except ServiceUnavailableError as exc:
            log.warning("train_fga_unavailable", extra={"token": token, "error": str(exc)})
            return _RETRY

    try:
        outcome = await ray_submit.submit_train_job(
            settings,
            model=model,
            features_json=json.dumps(features),
            config_json=json.dumps(data.get("config") or {}),
            token=token,
        )
    except ray_submit.RayJobError as exc:
        log.warning("train_submit_failed", extra={"token": token, "error": str(exc)})
        return _RETRY
    if outcome == "already_failed":
        log.warning("train_previously_failed", extra={"token": token, "model": model})
        return _DROP
    log.info("train_job_dispatched", extra={"token": token, "model": model, "outcome": outcome})
    return _SUCCESS
