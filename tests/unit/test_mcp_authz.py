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


async def test_default_mcp_role_blocks_recording_attestation(tmp_path, monkeypatch) -> None:
    """The AI/agent default role must never be able to mark a learner attested."""
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    from complyos.api.mcp_server import record_attestation

    with pytest.raises(AuthorizationError) as exc:
        await record_attestation(
            user_id="u1",
            requirement_id="ai-pol",
            policy_version="ai-use-policy-2026.1",
            db_path=str(tmp_path / "att.db"),
        )
    assert exc.value.permission == "attestation:record"


async def test_default_mcp_role_may_list_attestations(tmp_path, monkeypatch) -> None:
    """The agent role may read attestations so it can report un-attested learners."""
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    from complyos.api.mcp_server import list_attestations

    result = await list_attestations(db_path=str(tmp_path / "att-list.db"))
    assert result["items"] == []


def test_mcp_default_tenant_is_local_default(monkeypatch) -> None:
    """Without COMPLYOS_MCP_TENANT_ID, MCP keeps the single-tenant default."""
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    monkeypatch.delenv("COMPLYOS_MCP_TENANT_ID", raising=False)
    from complyos.api.mcp_server import _mcp_context

    context = _mcp_context()
    assert context.tenant_id == "local-default"


def test_mcp_tenant_id_env_var_pins_context(monkeypatch) -> None:
    """COMPLYOS_MCP_TENANT_ID overrides the default tenant for every MCP call."""
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    monkeypatch.setenv("COMPLYOS_MCP_TENANT_ID", "tenant-acme")
    from complyos.api.mcp_server import _mcp_context

    context = _mcp_context()
    assert context.tenant_id == "tenant-acme"


def test_mcp_tenant_id_env_var_blocks_cross_tenant_arg(monkeypatch) -> None:
    """A per-tool tenant_id that disagrees with the pinned tenant is rejected."""
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    monkeypatch.setenv("COMPLYOS_MCP_TENANT_ID", "tenant-acme")
    from complyos.api.mcp_server import _mcp_context

    with pytest.raises(ValueError, match="conflicts with COMPLYOS_MCP_TENANT_ID"):
        _mcp_context(tenant_id="tenant-other")
