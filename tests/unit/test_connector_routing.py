"""Connector factory routing tests."""

from __future__ import annotations

import pytest

from complyos.api import mcp_server
from complyos.api.mcp_server import _get_connector
from complyos.config import ComplyOSConfig
from complyos.connectors.base import ConnectorConfigurationError
from complyos.connectors.blackboard import BlackboardConnector
from complyos.connectors.brightspace import BrightspaceConnector
from complyos.connectors.canvas import CanvasConnector
from complyos.connectors.cornerstone import CornerstoneConnector
from complyos.connectors.moodle import MoodleConnector
from complyos.connectors.successfactors import SuccessFactorsConnector


def _clear_connector_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    for var in (
        "BRIGHTSPACE_BASE_URL",
        "BRIGHTSPACE_CLIENT_ID",
        "BRIGHTSPACE_CLIENT_SECRET",
        "BRIGHTSPACE_TOKEN_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_get_connector_routes_successfactors_config(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(lambda cls: ComplyOSConfig({"connector": {"type": "successfactors"}})),
    )

    assert isinstance(_get_connector(), SuccessFactorsConnector)


def test_get_connector_routes_cornerstone_config(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(lambda cls: ComplyOSConfig({"connector": {"type": "cornerstone"}})),
    )

    assert isinstance(_get_connector(), CornerstoneConnector)


def test_get_connector_routes_canvas_config(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(lambda cls: ComplyOSConfig({"connector": {"type": "canvas"}})),
    )

    assert isinstance(_get_connector(), CanvasConnector)


def test_get_connector_routes_brightspace_config(monkeypatch) -> None:
    _clear_connector_env(monkeypatch)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(lambda cls: ComplyOSConfig({"connector": {"type": "brightspace"}})),
    )

    assert isinstance(_get_connector(), BrightspaceConnector)


def test_get_connector_brightspace_creds_without_token_url_fail_closed(monkeypatch) -> None:
    """Adversary caveat 2 (2026-09-19): config type brightspace with client
    credentials but no token_url must raise a structured configuration error
    at connector construction — before any network dial to the previously
    hardcoded https://auth.brightspace.com endpoint."""
    _clear_connector_env(monkeypatch)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(
            lambda cls: ComplyOSConfig(
                {
                    "connector": {
                        "type": "brightspace",
                        "brightspace": {
                            "base_url": "https://school.brightspace.test",
                            "client_id": "fake-id",
                            "client_secret": "fake-secret",
                            # token_url deliberately absent
                        },
                    }
                }
            )
        ),
    )

    with pytest.raises(ConnectorConfigurationError, match="token_url"):
        _get_connector()


def test_get_connector_brightspace_creds_with_token_url_route(monkeypatch) -> None:
    """Explicit token_url in config keeps the brightspace route usable."""
    _clear_connector_env(monkeypatch)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(
            lambda cls: ComplyOSConfig(
                {
                    "connector": {
                        "type": "brightspace",
                        "brightspace": {
                            "base_url": "https://school.brightspace.test",
                            "client_id": "fake-id",
                            "client_secret": "fake-secret",
                            "token_url": "https://auth.brightspace.test/core/connect/token",
                        },
                    }
                }
            )
        ),
    )

    connector = _get_connector()
    assert isinstance(connector, BrightspaceConnector)
    assert connector.token_url == "https://auth.brightspace.test/core/connect/token"


def test_get_connector_routes_moodle_config(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(lambda cls: ComplyOSConfig({"connector": {"type": "moodle"}})),
    )

    assert isinstance(_get_connector(), MoodleConnector)


def test_get_connector_routes_blackboard_config(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(lambda cls: ComplyOSConfig({"connector": {"type": "blackboard"}})),
    )

    assert isinstance(_get_connector(), BlackboardConnector)
