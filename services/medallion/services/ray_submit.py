"""Submit a stage-transform Ray job to the ray-lance cluster via the Ray Jobs REST API.

The event-driven real-Ray path (``MEDALLION_RAY_ENABLED``): a mover submits ``scripts/ray_stage_job.py``
(baked into the ray-lance image) to the Ray cluster IN RESPONSE TO its Dapr cascade trigger, instead of the
in-process fake-Ray ``compute.transform_stage``. Uses only ``httpx`` against the Ray Jobs REST API — no
``ray`` package in the mover image.

Idempotent under at-least-once redelivery: the submission id is DETERMINISTIC per (stage, token), so a
redelivered trigger (the handler blocks until the job finishes, which can exceed the 30s ack window)
RE-ATTACHES to the same job and polls it, rather than starting a second concurrent job that would race the
write. A failure (submit error, FAILED job, or timeout) raises so the mover returns RETRY and the sidecar
redelivers; on redelivery a terminally FAILED/STOPPED job with the same id is DELETED and resubmitted fresh
(so the retry runs on a healthy worker rather than re-observing the same failure), while a still-running job
is re-attached and polled. Production KubeRay handles in-job task retry/orchestration.

Known limitation (assessment): the handler blocks until the job finishes, so a job that runs longer than
maxDeliver × ackWait (~2.5 min at the defaults) exhausts redelivery and the trigger is dropped with no DLQ —
the ray path suits bounded-duration stage transforms; genuinely long jobs need the async-completion redesign
(submit + ack, the job or a webhook triggers the next stage). See docs/RESILIENCE.md.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping

import httpx

from medallion.core.config import MedallionSettings

log = logging.getLogger(__name__)

_TERMINAL_OK = "SUCCEEDED"
_TERMINAL_BAD = frozenset({"FAILED", "STOPPED"})
# Tolerate a few transient poll blips (a 5xx / connect timeout) before giving up, so one bad GET doesn't
# abandon an in-flight job and trigger a redelivery that re-attaches anyway — bounded by the job timeout.
_MAX_POLL_ERRORS = 3


class RayJobError(RuntimeError):
    """A submitted Ray stage job failed, was stopped, or did not finish within the timeout."""


def _submission_id(stage: str, token: str | None) -> str:
    """A deterministic id per (stage, token) so redelivery re-attaches to the same job (idempotency)."""
    raw = f"ray-{stage}-{token or 'notoken'}"
    return re.sub(r"[^A-Za-z0-9_-]", "-", raw)[:200]


async def submit_stage_job(
    settings: MedallionSettings, *, from_uri: str, to_uri: str, stage: str, token: str | None
) -> None:
    """Submit (or re-attach to) the stage transform on the Ray cluster and block until it succeeds.

    Raises :class:`RayJobError` on a submit failure, a FAILED/STOPPED job, or a timeout — the caller maps
    that to RETRY. On success the downstream Lance dataset exists at ``to_uri`` and the caller measures it.
    """
    submission_id = _submission_id(stage, token)
    env_vars = {
        "FROM_URI": from_uri,
        "TO_URI": to_uri,
        "STAGE": stage,
        "S3_ENDPOINT": settings.s3_endpoint,
        "S3_KEY": settings.s3_access_key_id,
        "S3_SECRET": settings.s3_secret_access_key.get_secret_value(),
        "S3_REGION": settings.s3_region,
    }
    body = {
        "entrypoint": settings.ray_entrypoint,
        "submission_id": submission_id,
        "runtime_env": {"env_vars": env_vars},
    }

    async with httpx.AsyncClient(
        base_url=settings.ray_address, timeout=settings.ray_request_timeout_seconds
    ) as client:
        await _submit_or_reattach(client, submission_id, body)
        log.info("ray_stage_job_submitted", extra={"submission_id": submission_id, "stage": stage})
        try:
            async with asyncio.timeout(settings.ray_job_timeout_seconds):
                await _await_success(client, submission_id, settings.ray_poll_interval_seconds)
        except TimeoutError as exc:
            raise RayJobError(
                f"ray stage job {submission_id} did not finish within {settings.ray_job_timeout_seconds}s"
            ) from exc
    log.info("ray_stage_job_succeeded", extra={"submission_id": submission_id, "stage": stage})


async def _submit_or_reattach(
    client: httpx.AsyncClient, submission_id: str, body: Mapping[str, object]
) -> None:
    """POST /api/jobs/. A 4xx when the id already exists (idempotent redelivery) re-attaches to that job —
    UNLESS that prior job terminally FAILED/STOPPED, in which case it is deleted and resubmitted fresh so the
    redelivery actually retries the transform on a healthy worker (instead of re-observing the same failure
    every redelivery until maxDeliver silently drops the trigger — the deterministic-id poison)."""
    try:
        response = await client.post("/api/jobs/", json=dict(body))
        if response.status_code < 400:
            return
        # Already-submitted (redelivery): inspect the existing job to decide re-attach vs fresh retry.
        existing = await client.get(f"/api/jobs/{submission_id}")
        if existing.status_code == 200:
            status = existing.json().get("status")
            if status in _TERMINAL_BAD:
                # DELETE is only valid on a terminal job (FAILED/STOPPED are), then re-POST the same id.
                await client.delete(f"/api/jobs/{submission_id}")
                fresh = await client.post("/api/jobs/", json=dict(body))
                fresh.raise_for_status()
                log.info("ray_stage_job_resubmitted_after_failure", extra={"submission_id": submission_id})
                return
            log.info("ray_stage_job_reattach", extra={"submission_id": submission_id})
            return
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise RayJobError(f"failed to submit ray stage job {submission_id}: {exc}") from exc


async def _await_success(client: httpx.AsyncClient, submission_id: str, poll_interval: float) -> None:
    """Poll GET /api/jobs/{id} until SUCCEEDED; raise on FAILED/STOPPED. Bounded by the caller's timeout."""
    poll_errors = 0
    while True:
        await asyncio.sleep(poll_interval)
        try:
            response = await client.get(f"/api/jobs/{submission_id}")
            response.raise_for_status()
        except httpx.HTTPError as exc:
            poll_errors += 1
            if poll_errors > _MAX_POLL_ERRORS:
                raise RayJobError(f"failed to poll ray stage job {submission_id}: {exc}") from exc
            continue
        poll_errors = 0
        payload = response.json()
        status = payload.get("status")
        if status == _TERMINAL_OK:
            return
        if status in _TERMINAL_BAD:
            raise RayJobError(f"ray stage job {submission_id} {status}: {payload.get('message')}")
