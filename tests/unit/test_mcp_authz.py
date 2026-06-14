"""MCP least-privilege authorization tests (WP3 / H3).

The MCP surface must default to a proposal-only role so a connected AI agent
cannot delete subjects, approve controller decisions, or auto-remediate unless
an operator explicitly raises COMPLYOS_MCP_ROLE.
"""

from __future__ import annotations

import pytest

from complyos.services.context import AuthorizationError


async def test_default_mcp_role_blocks_subject_deletion(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    from complyos.api.mcp_server import delete_privacy_subject

    with pytest.raises(AuthorizationError):
        await delete_privacy_subject(request_id="any", db_path=str(tmp_path / "a.db"))


async def test_default_mcp_role_blocks_remediation(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    from complyos.api.mcp_server import remediate_compliance_gaps

    with pytest.raises(AuthorizationError):
        await remediate_compliance_gaps()


async def test_default_mcp_role_allows_proposal_only_work(tmp_path, monkeypatch) -> None:
    """The default agent role can still do its proposal-only job (e.g. audit)."""
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    from complyos.api.mcp_server import audit_compliance_gaps

    result = await audit_compliance_gaps()
    assert "gaps_found" in result


async def test_explicit_role_opt_in_allows_privileged_op(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMPLYOS_MCP_ROLE", "privacy_admin")
    from complyos.api.mcp_server import create_privacy_request

    result = await create_privacy_request(
        subject_id="u1", request_type="access", db_path=str(tmp_path / "b.db")
    )
    assert result["subject_id"] == "u1"


def test_unknown_mcp_role_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("COMPLYOS_MCP_ROLE", "nonsense-role")
    from complyos.api.mcp_server import _mcp_context

    with pytest.raises(ValueError, match="unknown COMPLYOS_MCP_ROLE"):
        _mcp_context()
