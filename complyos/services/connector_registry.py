"""Service wrapper for connector capability/matrix listing and health checks.

The CLI `connectors`/`health` commands, the MCP `check_connector_health` tool,
and the API `/connectors/health` route used to call the capabilities module and
the connector `health_check()` directly while enforcing permissions only at the
surface (and the list surface enforced nothing). This service makes the service
layer the single authorization choke-point: both methods accept an ActorContext
and call require_permission(connectors:read) before touching connector code.
Return shapes match what the surfaces produced before the wrapper existed.
"""

from __future__ import annotations

from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.connectors.capabilities import list_connector_capabilities
from complyos.services.context import (
    PERM_CONNECTORS_READ,
    ActorContext,
    require_permission,
)


class ConnectorRegistry:
    """Authorization-gated connector capability matrix and health checks."""

    def __init__(self, connector: LMSConnector) -> None:
        self.connector = connector

    def list(
        self,
        context: ActorContext,
        *,
        profile: str | None = None,
    ) -> list[dict[str, str | bool]]:
        """List the connector capability matrix, optionally filtered by profile."""
        require_permission(context, PERM_CONNECTORS_READ)
        return [item.to_dict() for item in list_connector_capabilities(profile=profile)]

    async def health(self, context: ActorContext) -> dict[str, Any]:
        """Return the configured connector's health status."""
        require_permission(context, PERM_CONNECTORS_READ)
        return await self.connector.health_check()
