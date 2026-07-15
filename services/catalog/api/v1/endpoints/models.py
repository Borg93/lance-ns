"""#17 model-registry endpoints: candidate→blessed promotion + a describe / serving read.

The model registry is a Lance dataset per model at ``settings.model_uri(model)`` (the medallion trainer
writes it there directly). These routes live OUTSIDE the router-level ``authorize`` coverage (``/v1/model``
is not an FGA ``_RESOURCES`` prefix), so OIDC is still enforced by the ``CurrentToken`` dependency, but the
FGA gate is EXPLICIT per handler: promote → the VALIDATOR rung ``can_promote``; describe → the reader rung
``can_get_metadata`` — both on ``table:models$<model>`` (the per-model FGA object the trainer seeds at train
time, so the rung cascades from ``namespace:models``). Promotion moves the ``blessed`` Lance tag after a
fail-closed metrics gate; a distinct promotion RunEvent is emitted best-effort so the blessing lands in
lineage without being mistaken for a training run.
"""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Header
from fastapi.concurrency import run_in_threadpool
from lance_namespace import InvalidInputError
from pydantic import BaseModel, ConfigDict, Field

from catalog.api import fga_deps
from catalog.api.dependencies import FgaClientDep, LineageEmitterDep, SettingsDep, StorageOptionsDep
from catalog.api.security import CurrentToken
from catalog.core.lineage_emit import PROMOTE_MODEL, emit_write_event
from catalog.services import models as registry

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/model", tags=["model"])

# The FGA namespace the per-model object lives under (``table:<ns>$<model>``) — matches the medallion
# trainer's MEDALLION_MODELS_NAMESPACE default + scripts/seed_medallion_fga.sh. A model name is a
# table-name-shaped fragment (kept strict so it can't traverse the registry path or forge an FGA object id).
_MODELS_NAMESPACE = "models"
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _segments(model: str) -> list[str]:
    if not _MODEL_RE.match(model):
        raise InvalidInputError(f"invalid model name: {model!r}")
    return [_MODELS_NAMESPACE, model]


class PromoteRequest(BaseModel):
    """Bless a candidate model version (candidate→blessed). ``version`` is the model/Lance version to bless;
    ``min_metrics`` is the fail-closed gate — each named metric must be present AND >= its threshold."""

    version: int = Field(ge=1)
    min_metrics: dict[str, float] = Field(default_factory=dict)
    tag: str = Field(default=registry.BLESSED_TAG, min_length=1, max_length=64)


class PromoteResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model: str
    blessed_version: int
    tag: str


class ModelDescribeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model: str
    latest_version: int
    blessed_version: int | None
    candidate_metrics: dict[str, Any]
    blessed_metrics: dict[str, Any] | None


@router.post("/{model}/promote", response_model_exclude_none=True)
async def promote_model(
    model: str,
    body: PromoteRequest,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    client: FgaClientDep,
    emitter: LineageEmitterDep,
    authorization: Annotated[str | None, Header()] = None,
) -> PromoteResponse:
    """Move the ``blessed`` tag to model ``version`` — validator-gated, metrics-gated, lineage-emitting.

    Authorization is the VALIDATOR rung (``can_promote``), a deliberately higher bar than a plain writer:
    training PUBLISHES candidates (writer), a validator BLESSES one (the model analog of silver→gold). The
    metrics gate runs inside the fail-closed promote op BEFORE the irreversible tag move; the promotion
    RunEvent is best-effort AFTER (a lineage outage never fails a promotion).
    """
    segments = _segments(model)
    await fga_deps.require_can_promote(client, settings, token, segments=segments)
    blessed = await run_in_threadpool(
        registry.promote,
        settings.model_uri(model),
        so,
        version=body.version,
        min_metrics=body.min_metrics or None,
        tag=body.tag,
    )
    await emit_write_event(
        emitter,
        segments,
        delimiter=settings.delimiter,
        author=token.sub if token is not None else None,
        version=blessed,
        operation=PROMOTE_MODEL,
        authorization=authorization,
        source_uri=settings.model_uri(model),
    )
    log.info("model_promoted", extra={"model": model, "version": blessed, "tag": body.tag})
    return PromoteResponse(model=model, blessed_version=blessed, tag=body.tag)


@router.get("/{model}", response_model_exclude_none=True)
async def describe_model(
    model: str,
    settings: SettingsDep,
    so: StorageOptionsDep,
    token: CurrentToken,
    client: FgaClientDep,
) -> ModelDescribeResponse:
    """Registry summary: the latest (candidate) version, the blessed version (or null), and both metrics.

    Reader-gated (``can_get_metadata``) — a reader may see which version is blessed and compare metrics; only
    a validator may move the pointer.
    """
    segments = _segments(model)
    await fga_deps.require_can_get_metadata(client, settings, token, segments=segments)
    summary = await run_in_threadpool(registry.describe, settings.model_uri(model), so)
    return ModelDescribeResponse(model=model, **summary)
