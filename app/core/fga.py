"""Fine-grained authorization via OpenFGA (Zanzibar-style relationship checks).

The authorization model (``app/auth/model.fga`` / ``model.json``) defines
``namespace`` and ``table`` types with ``reader``/``writer``/``owner`` relations,
where a table inherits from its parent namespace. OpenFGA stores its tuples in
Postgres (the ``migrate``/``run`` services in docker-compose).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openfga_sdk import ClientConfiguration, OpenFgaClient
from openfga_sdk.client.models import (
    ClientBatchCheckItem,
    ClientBatchCheckRequest,
    ClientCheckRequest,
    ClientListObjectsRequest,
    ClientTuple,
    ClientWriteRequest,
)
from openfga_sdk.models.create_store_request import CreateStoreRequest
from openfga_sdk.models.write_authorization_model_request import WriteAuthorizationModelRequest

_MODEL_PATH = Path(__file__).resolve().parent.parent / "auth" / "model.json"


def load_model() -> dict[str, Any]:
    """Load the authorization model JSON shipped with the app."""
    return json.loads(_MODEL_PATH.read_text())


async def provision(api_url: str, *, store_name: str = "lance-catalog") -> tuple[str, str]:
    """Create a store and write the catalog model; return ``(store_id, model_id)``.

    For dev / e2e where ids aren't pinned. In production, provision once and pin
    ``LANCE_FGA_STORE_ID`` + ``LANCE_FGA_MODEL_ID`` (the model is versioned).
    """
    model = load_model()
    async with OpenFgaClient(ClientConfiguration(api_url=api_url)) as client:
        store = await client.create_store(CreateStoreRequest(name=store_name))
    async with OpenFgaClient(ClientConfiguration(api_url=api_url, store_id=store.id)) as client:
        written = await client.write_authorization_model(
            WriteAuthorizationModelRequest(
                schema_version=model["schema_version"],
                type_definitions=model["type_definitions"],
            )
        )
    return store.id, written.authorization_model_id


def make_client(api_url: str, store_id: str, model_id: str) -> OpenFgaClient:
    """Build an OpenFGA client pinned to a store + authorization model."""
    return OpenFgaClient(
        ClientConfiguration(api_url=api_url, store_id=store_id, authorization_model_id=model_id)
    )


async def check(client: OpenFgaClient, *, user: str, relation: str, obj: str) -> bool:
    """Return whether ``user:<user>`` has ``relation`` on ``obj`` (e.g. ``table:db1$t``)."""
    response = await client.check(ClientCheckRequest(user=f"user:{user}", relation=relation, object=obj))
    return bool(response.allowed)


async def batch_check(
    client: OpenFgaClient, *, user: str, relation: str, objects: list[str]
) -> dict[str, bool]:
    """Return ``{object: allowed}`` for one user across many objects in one round-trip."""
    items = [ClientBatchCheckItem(user=f"user:{user}", relation=relation, object=o) for o in objects]
    response = await client.batch_check(ClientBatchCheckRequest(checks=items))
    return {r.request.object: bool(r.allowed) for r in response.result}


async def list_objects(client: OpenFgaClient, *, user: str, relation: str, object_type: str) -> list[str]:
    """Return the objects of ``object_type`` the user has ``relation`` on (e.g. ``table:…``)."""
    response = await client.list_objects(
        ClientListObjectsRequest(user=f"user:{user}", relation=relation, type=object_type)
    )
    return list(response.objects)


async def write_tuples(client: OpenFgaClient, tuples: list[ClientTuple]) -> None:
    """Persist relationship tuples (the single write path after a successful mutation)."""
    await client.write(ClientWriteRequest(writes=tuples))
