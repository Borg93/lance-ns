"""The mover's Dapr pub/sub subscription route (``/medallion-event``).

The :class:`DaprApp` wrapper serves ``GET /dapr/subscribe`` (read by the sidecar at startup) and routes
deliveries of the mover's ``sub_topic`` to :func:`handle_stage`. Each mover has its own app-id + sub_topic,
so no consumer clash. Authenticated by the Dapr app-api-token (``require_dapr_token``) so a forged stage
trigger can't drive the cascade. :func:`register_stage_route` wires it onto a mover app from the thin entry.
"""

from __future__ import annotations

from typing import Annotated, Any

from common.dapr_auth import require_dapr_token
from dapr.ext.fastapi import DaprApp
from fastapi import Depends, FastAPI

from medallion.api.dependencies import DaprClientDep, FgaClientDep, SettingsDep
from medallion.core.config import get_settings
from medallion.services.transform import handle_stage


def register_stage_route(app: FastAPI) -> DaprApp:
    """Wrap ``app`` in a :class:`DaprApp` and register the mover's stage subscription handler."""
    settings = get_settings()
    dapr_app = DaprApp(app)

    @dapr_app.subscribe(pubsub=settings.pubsub, topic=settings.sub_topic, route="/medallion-event")
    async def on_stage(
        event: dict[str, Any],
        dapr: DaprClientDep,
        config: SettingsDep,
        fga_client: FgaClientDep,
        _: Annotated[None, Depends(require_dapr_token)],
    ) -> dict[str, str]:
        """The Dapr subscription route — thin wrapper over the testable :func:`handle_stage`. ``event``
        is typed ``dict`` so FastAPI parses the CloudEvent JSON body (an ``Any`` param → query param →
        422). Authenticated by the Dapr app-api-token so a forged stage trigger can't drive the cascade."""
        return await handle_stage(dapr, config, event, fga_client=fga_client)

    return dapr_app
