"""Connector factory routing tests."""

from __future__ import annotations

from complyos.api import mcp_server
from complyos.api.mcp_server import _get_connector
from complyos.config import ComplyOSConfig
from complyos.connectors.blackboard import BlackboardConnector
from complyos.connectors.brightspace import BrightspaceConnector
from complyos.connectors.canvas import CanvasConnector
from complyos.connectors.cornerstone import CornerstoneConnector
from complyos.connectors.moodle import MoodleConnector
from complyos.connectors.successfactors import SuccessFactorsConnector


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
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    monkeypatch.setattr(
        mcp_server.ComplyOSConfig,
        "load",
        classmethod(lambda cls: ComplyOSConfig({"connector": {"type": "brightspace"}})),
    )

    assert isinstance(_get_connector(), BrightspaceConnector)


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
