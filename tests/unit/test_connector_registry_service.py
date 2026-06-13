"""ConnectorRegistry service-wrapper authorization and shape-parity tests (WP11).

ConnectorRegistry is the single authorization choke-point for the connector
capability matrix (list) and connector health (health). Both enforce
connectors:read and fail closed for an under-privileged context, while
returning the same shapes the CLI/MCP/API surfaces produced before the wrapper
existed.
"""

from __future__ import annotations

import pytest

from complyos.connectors.capabilities import list_connector_capabilities
from complyos.connectors.mock import MockConnector
from complyos.services.connector_registry import ConnectorRegistry
from complyos.services.context import AuthorizationError, default_local_context


def _service() -> ConnectorRegistry:
    return ConnectorRegistry(MockConnector())


def test_list_requires_connectors_read_and_fails_closed() -> None:
    service = _service()
    # read_only lacks connectors:read.
    context = default_local_context(surface="api", role="read_only")

    with pytest.raises(AuthorizationError) as exc:
        service.list(context)

    assert exc.value.permission == "connectors:read"


def test_list_for_authorized_context_matches_capability_matrix() -> None:
    service = _service()
    context = default_local_context(surface="cli", role="compliance_manager")

    result = service.list(context)

    expected = [item.to_dict() for item in list_connector_capabilities(profile=None)]
    assert result == expected


def test_list_filters_by_profile() -> None:
    service = _service()
    context = default_local_context(surface="cli", role="owner")

    result = service.list(context, profile="campus")

    expected = [item.to_dict() for item in list_connector_capabilities(profile="campus")]
    assert result == expected
    assert all(item["profile"] in {"campus", "both"} for item in result)


def test_list_rejects_unknown_profile() -> None:
    service = _service()
    context = default_local_context(surface="cli", role="owner")

    with pytest.raises(ValueError):
        service.list(context, profile="nonsense")


async def test_health_requires_connectors_read_and_fails_closed() -> None:
    service = _service()
    context = default_local_context(surface="api", role="read_only")

    with pytest.raises(AuthorizationError) as exc:
        await service.health(context)

    assert exc.value.permission == "connectors:read"


async def test_health_for_authorized_context_returns_connector_status() -> None:
    service = _service()
    context = default_local_context(surface="mcp", role="agent_service_account")

    result = await service.health(context)

    expected = await MockConnector().health_check()
    assert result == expected
    assert "connector" in result
    assert "status" in result
