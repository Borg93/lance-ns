"""Credential vending — hand an authorized client scoped ``storage_options`` for DIRECT object I/O.

Track B: instead of every byte flowing through the catalog (Mode B, the server-mediated Arrow-IPC path),
an authorized caller can request short-TTL, per-table, tier-scoped credentials and read/write the Lance
data on object storage itself (LanceDB SDK / lance-ray / pylance). The vendor plug is chosen at boot
(``LANCE_VENDING_MODE``): ``sts`` (AssumeRole + a per-table session policy — the recommended path),
``static`` (per-bucket keys), or ``mode_b`` (vends nothing → the client uses the data endpoints).

Authz: the router-level :func:`catalog.api.fga_deps.authorize` already required ``can_read_data`` on the
table (``credentials`` is mapped to the reader-data rung); a ``tier=write`` request additionally requires
``can_write_data`` here. So a reader gets read-scoped creds and a writer gets write-scoped creds — the
session policy then enforces the same scope at the object store.
"""

from __future__ import annotations

from typing import Annotated

from botocore.exceptions import BotoCoreError, ClientError
from common import fga
from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from lance_namespace import (
    DescribeTableRequest,
    DescribeTableResponse,
    PermissionDeniedError,
    ServiceUnavailableError,
    UnauthenticatedError,
)
from pydantic import BaseModel

from catalog.api.dependencies import FgaClientDep, NamespaceDep, SettingsDep, VendorDep
from catalog.api.security import CurrentToken, RawBearerToken
from catalog.core.identifiers import parse_identifier
from catalog.core.vending import Tier, VendedCredentials
from catalog.services import native

router = APIRouter(prefix="/v1/table", tags=["credentials"])


class CredentialResponse(BaseModel):
    """The vending result. ``mode="direct"`` carries scoped ``credentials``; ``mode="server_mediated"``
    means no credential was issued (Mode B / unknown bucket) — the client uses the data endpoints."""

    mode: str
    credentials: VendedCredentials | None = None


@router.post("/{id}/credentials", response_model_exclude_none=True)
async def vend_credentials(
    id: str,
    ns: NamespaceDep,
    settings: SettingsDep,
    token: CurrentToken,
    client: FgaClientDep,
    vendor: VendorDep,
    web_identity_token: RawBearerToken,
    tier: Annotated[Tier, Query()] = "read",
) -> CredentialResponse:
    """Vend scoped ``storage_options`` for direct object-store access to this table at ``tier``.

    ``web_identity_token`` is the caller's raw bearer JWT (via the shared HTTPBearer seam), forwarded to the
    object store for the web_identity flow (AssumeRoleWithWebIdentity exchanges it); other vendors ignore it.
    """
    segments = parse_identifier(id, settings.delimiter)
    # A write-tier vend needs the writer rung on top of the reader rung the router guard enforced.
    if tier == "write" and settings.fga_enabled and token is not None and client is not None:
        obj = f"table:{fga.canonical_object_id(segments, delimiter=settings.delimiter)}"
        if not await fga.check(client, user=token.sub, relation="can_write_data", obj=obj):
            raise PermissionDeniedError(f"can_write_data required on {obj} for a write-tier credential")
    described: DescribeTableResponse = await run_in_threadpool(
        native.call, ns, "describe_table", DescribeTableRequest(id=segments)
    )
    if described.location is None:  # no object-store location to scope to → fall back to server-mediated
        return CredentialResponse(mode="server_mediated")
    # The blocking STS call (AssumeRole / AssumeRoleWithWebIdentity) runs in the threadpool. A rejected
    # exchange is most often the caller's token (web_identity: expired / untrusted issuer) → 401; otherwise
    # the STS backend is unavailable/misconfigured → 503. Either way a meaningful 4xx/5xx, never a bare 500.
    try:
        creds = await run_in_threadpool(
            vendor.vend, table_location=described.location, tier=tier, web_identity_token=web_identity_token
        )
    except (ClientError, BotoCoreError) as exc:
        if settings.vending_mode == "web_identity":
            raise UnauthenticatedError("credential exchange rejected — token invalid or untrusted") from exc
        raise ServiceUnavailableError("credential vending backend unavailable") from exc
    if creds is None:
        return CredentialResponse(mode="server_mediated")
    return CredentialResponse(mode="direct", credentials=creds)
