"""Cross-surface authorization parity (plan §13.2).

A forbidden action must be denied identically whether it is attempted via the
service layer, the HTTP API, or an MCP tool — same permission, same fail-closed
result. This complements the per-surface authz tests by proving the three
surfaces cannot drift into different authorization behavior.

The two actions exercised:
- ``remediation:execute`` (under-privileged actor: ``read_only``)
- ``import:promote``     (under-privileged actor: ``importer`` — has preview/decide)
On MCP the default ``agent_service_account`` role lacks both, so its tools fail
closed without any role opt-in.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from complyos.api.mcp_server import promote_import_batch, remediate_compliance_gaps
from complyos.connectors.mock import MockConnector
from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_IMPORT_PROMOTE,
    PERM_REMEDIATION_EXECUTE,
    AuthorizationError,
    default_local_context,
)
from complyos.services.imports import ImportService
from complyos.services.remediation import RemediationService
from complyos.web.api_v1 import create_api_v1_app

_FULL_REMEDIATION_BODY = {
    "department": None,
    "region": None,
    "auto_remind": False,
    "auto_enroll": False,
    "notify_manager": False,
}


def _insecure_client(monkeypatch, tmp_path, name: str) -> TestClient:
    monkeypatch.delenv("COMPLYOS_API_TOKEN", raising=False)
    monkeypatch.setenv("COMPLYOS_ALLOW_INSECURE_LOCAL", "1")
    return TestClient(create_api_v1_app(LocalRepository(str(tmp_path / name))))


# --- remediation:execute denied on all three surfaces -----------------------


async def test_remediation_execute_denied_in_service_layer() -> None:
    ctx = default_local_context(surface="cli", role="read_only")
    with pytest.raises(AuthorizationError) as exc:
        await RemediationService(MockConnector()).execute(ctx)
    assert exc.value.permission == PERM_REMEDIATION_EXECUTE
    assert exc.value.code == "permission_denied"


def test_remediation_execute_denied_on_api(monkeypatch, tmp_path) -> None:
    client = _insecure_client(monkeypatch, tmp_path, "xsurface-rem.db")
    resp = client.post(
        "/api/v1/remediations",
        json=_FULL_REMEDIATION_BODY,
        headers={"X-Actor-Role": "read_only"},
    )
    assert resp.status_code == 403
    assert "permission_denied" in resp.text


async def test_remediation_execute_denied_on_mcp(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    with pytest.raises(AuthorizationError) as exc:
        await remediate_compliance_gaps()
    assert exc.value.permission == PERM_REMEDIATION_EXECUTE


# --- import:promote denied on all three surfaces ----------------------------


def test_import_promote_denied_in_service_layer(tmp_path) -> None:
    # importer holds import:preview + import:decide but NOT import:promote.
    ctx = default_local_context(surface="cli", role="importer")
    with pytest.raises(AuthorizationError) as exc:
        ImportService(LocalRepository(str(tmp_path / "xsurface-imp.db"))).promote(ctx, "no-batch")
    assert exc.value.permission == PERM_IMPORT_PROMOTE
    assert exc.value.code == "permission_denied"


def test_import_promote_denied_on_api(monkeypatch, tmp_path) -> None:
    client = _insecure_client(monkeypatch, tmp_path, "xsurface-imp-api.db")
    # Permission is checked before the batch lookup, so a missing batch still 403s.
    resp = client.post(
        "/api/v1/imports/no-batch/promote",
        headers={"X-Actor-Role": "importer"},
    )
    assert resp.status_code == 403
    assert "permission_denied" in resp.text


async def test_import_promote_denied_on_mcp(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    with pytest.raises(AuthorizationError) as exc:
        await promote_import_batch("no-batch", db_path=str(tmp_path / "xsurface-mcp.db"))
    assert exc.value.permission == PERM_IMPORT_PROMOTE
