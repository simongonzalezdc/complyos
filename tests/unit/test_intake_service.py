"""Unit + cross-surface tests for the training-intake module.

Covers the suite-module shape (capture -> proposal-only draft packet ->
human-confirmed scope -> action log) and its guardrails: the proposal-only/agent
role can draft + list but is DENIED confirm, tenant scoping blocks cross-tenant
read/confirm, the packet never confirms scope, and the language stays in the
readiness/scope lane (no "compliant"/"certified"). Mirrors the conventions in
``test_attestation_service.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.models.domain import IntakePriority, IntakeStatus
from complyos.services.context import (
    AuthorizationError,
    default_local_context,
)
from complyos.services.intake import IntakeService


def _repo(tmp_path) -> LocalRepository:
    return LocalRepository(str(tmp_path / "intake.db"))


def _ctx(
    *,
    role: str = "compliance_manager",
    tenant_id: str = "local-default",
    surface: str = "cli",
):
    return default_local_context(surface=surface, role=role, tenant_id=tenant_id)


def _agent_ctx(*, tenant_id: str = "local-default"):
    return default_local_context(surface="mcp", role="agent_service_account", tenant_id=tenant_id)


# --------------------------------------------------------------------------- #
# Capture
# --------------------------------------------------------------------------- #


def test_create_request_starts_in_draft(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(),
        requester="ops-lead",
        title="Quarterly safety refresher",
    )
    assert request.status is IntakeStatus.DRAFT
    assert request.is_confirmed is False
    assert request.confirmed_by is None
    assert request.tenant_id == "local-default"


def test_create_request_requires_title_and_requester(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    with pytest.raises(ValueError):
        service.create_request(_ctx(), requester="ops", title="   ")
    with pytest.raises(ValueError):
        service.create_request(_ctx(), requester="  ", title="A request")


def test_create_request_rejects_unknown_priority(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    with pytest.raises(ValueError):
        service.create_request(
            _ctx(), requester="ops", title="Thing", priority="catastrophic"
        )


# --------------------------------------------------------------------------- #
# Draft packet (proposal-only)
# --------------------------------------------------------------------------- #


def test_draft_packet_flags_missing_info(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(), requester="ops", title="A vague ask"
    )
    packet = service.draft_packet(_ctx(), request_id=request.id)
    # audience, business_context, constraints, requested_by_date all absent.
    assert set(packet.missing_info) == {
        "audience",
        "business_context",
        "constraints",
        "requested_by_date",
    }
    assert packet.is_complete is False


def test_draft_packet_complete_request_has_no_missing_info(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(),
        requester="ops",
        title="Manager coaching program",
        audience="All people managers",
        business_context="New management framework rollout",
        constraints="Must finish before Q3 reviews",
        requested_by_date=date.today() + timedelta(days=60),
    )
    packet = service.draft_packet(_ctx(), request_id=request.id)
    assert packet.missing_info == []
    assert packet.is_complete is True


def test_draft_packet_never_confirms_scope(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(_ctx(), requester="ops", title="Anything")
    packet = service.draft_packet(_ctx(), request_id=request.id)
    assert packet.confirms_scope is False
    assert packet.requires_human_confirmation is True
    # Drafting did not change the persisted request status.
    stored = service.repository.get_intake_request(request.id)
    assert stored is not None
    assert stored.status is IntakeStatus.DRAFT


def test_draft_packet_suggests_urgent_priority_for_near_term_date(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(),
        requester="ops",
        title="Same-week ask",
        requested_by_date=date.today() + timedelta(days=3),
    )
    packet = service.draft_packet(_ctx(), request_id=request.id)
    assert packet.suggested_priority is IntakePriority.URGENT


def test_draft_packet_routes_compliance_language_to_compliance_queue(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(),
        requester="ops",
        title="New regulatory compliance policy training",
    )
    packet = service.draft_packet(_ctx(), request_id=request.id)
    assert packet.suggested_routing == "compliance-training"


def test_draft_packet_defaults_routing_when_no_keyword(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(), requester="ops", title="A general request with no signal"
    )
    packet = service.draft_packet(_ctx(), request_id=request.id)
    assert packet.suggested_routing == "instructional-design"


def test_explicit_priority_is_preserved_in_packet(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(), requester="ops", title="Thing", priority="low"
    )
    packet = service.draft_packet(_ctx(), request_id=request.id)
    assert packet.suggested_priority is IntakePriority.LOW


# --------------------------------------------------------------------------- #
# Human-approval / confirm gate
# --------------------------------------------------------------------------- #


def test_confirm_scope_moves_draft_to_confirmed(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(_ctx(), requester="ops", title="Thing")
    confirmed = service.confirm_scope(_ctx(), request_id=request.id, note="approved by L&D owner")
    assert confirmed.status is IntakeStatus.CONFIRMED
    assert confirmed.is_confirmed is True
    assert confirmed.confirmed_by == "local-compliance_manager"
    assert confirmed.confirmed_at is not None
    assert confirmed.confirmation_note == "approved by L&D owner"


def test_confirmed_request_cannot_be_reconfirmed(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(_ctx(), requester="ops", title="Thing")
    service.confirm_scope(_ctx(), request_id=request.id)
    with pytest.raises(ValueError):
        service.confirm_scope(_ctx(), request_id=request.id)


def test_confirm_unknown_request_raises(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    with pytest.raises(ValueError):
        service.confirm_scope(_ctx(), request_id="does-not-exist")


# --------------------------------------------------------------------------- #
# Authorization split: agent can draft + list, but is DENIED confirm
# --------------------------------------------------------------------------- #


def test_agent_role_can_create_and_draft(tmp_path) -> None:
    """The proposal-only agent role holds intake:submit (draft + read side)."""
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(_agent_ctx(), requester="ops", title="Agent-captured ask")
    packet = service.draft_packet(_agent_ctx(), request_id=request.id)
    assert request.status is IntakeStatus.DRAFT
    assert packet.confirms_scope is False
    assert service.list_requests(_agent_ctx())


def test_agent_role_cannot_confirm_scope(tmp_path) -> None:
    """The agent role lacks intake:confirm — confirming scope is human-only."""
    repo = _repo(tmp_path)
    service = IntakeService(repo)
    request = service.create_request(_ctx(), requester="ops", title="Thing")

    with pytest.raises(AuthorizationError) as exc:
        service.confirm_scope(_agent_ctx(), request_id=request.id)
    assert exc.value.permission == "intake:confirm"

    # The denied call left the request unconfirmed.
    stored = repo.get_intake_request(request.id)
    assert stored is not None
    assert stored.status is IntakeStatus.DRAFT
    assert stored.confirmed_by is None


def test_read_only_role_cannot_submit_intake(tmp_path) -> None:
    """read_only lacks intake:submit; it is an audit/evidence reviewer, not intake."""
    service = IntakeService(_repo(tmp_path))
    with pytest.raises(AuthorizationError) as exc:
        service.create_request(
            _ctx(role="read_only"), requester="ops", title="Thing"
        )
    assert exc.value.permission == "intake:submit"


# --------------------------------------------------------------------------- #
# Tenant scoping
# --------------------------------------------------------------------------- #


def test_list_requests_is_tenant_scoped(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    service.create_request(_ctx(tenant_id="tenant-a"), requester="a", title="A request")
    service.create_request(_ctx(tenant_id="tenant-b"), requester="b", title="B request")

    a_items = service.list_requests(_ctx(tenant_id="tenant-a"))
    b_items = service.list_requests(_ctx(tenant_id="tenant-b"))
    assert [r.title for r in a_items] == ["A request"]
    assert [r.title for r in b_items] == ["B request"]


def test_cannot_confirm_request_in_another_tenant(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(_ctx(tenant_id="tenant-a"), requester="a", title="A request")
    # A context scoped to tenant-b must not confirm tenant-a's request.
    with pytest.raises(PermissionError):
        service.confirm_scope(_ctx(tenant_id="tenant-b"), request_id=request.id)


def test_cannot_draft_packet_for_another_tenant(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(_ctx(tenant_id="tenant-a"), requester="a", title="A request")
    with pytest.raises(PermissionError):
        service.draft_packet(_ctx(tenant_id="tenant-b"), request_id=request.id)


# --------------------------------------------------------------------------- #
# Action log
# --------------------------------------------------------------------------- #


def test_lifecycle_writes_action_log_trail(tmp_path) -> None:
    repo = _repo(tmp_path)
    service = IntakeService(repo)
    request = service.create_request(_ctx(), requester="ops", title="Thing")
    service.draft_packet(_ctx(), request_id=request.id)
    service.confirm_scope(_ctx(), request_id=request.id)

    actions = {log["action"] for log in repo.list_action_logs(tenant_id="local-default")}
    assert {
        "intake.request.create",
        "intake.packet.draft",
        "intake.scope.confirm",
    } <= actions


def test_list_filters_by_status(tmp_path) -> None:
    service = IntakeService(_repo(tmp_path))
    confirmed = service.create_request(_ctx(), requester="ops", title="Confirmed one")
    service.create_request(_ctx(), requester="ops", title="Still a draft")
    service.confirm_scope(_ctx(), request_id=confirmed.id)

    drafts = service.list_requests(_ctx(), status="draft")
    confirmeds = service.list_requests(_ctx(), status=IntakeStatus.CONFIRMED)
    assert [r.title for r in drafts] == ["Still a draft"]
    assert [r.title for r in confirmeds] == ["Confirmed one"]


# --------------------------------------------------------------------------- #
# Claim boundary — language stays in the scope/readiness lane
# --------------------------------------------------------------------------- #


def test_intake_outputs_make_no_compliance_or_certification_claim(tmp_path) -> None:
    """A confirmed request + packet must not assert anyone is compliant/certified."""
    service = IntakeService(_repo(tmp_path))
    request = service.create_request(
        _ctx(),
        requester="ops",
        title="New regulatory compliance policy training",
        business_context="Audit found a mandatory policy gap",
    )
    packet = service.draft_packet(_ctx(), request_id=request.id)
    confirmed = service.confirm_scope(_ctx(), request_id=request.id, note="ok")

    blob = (
        packet.model_dump_json().lower() + confirmed.model_dump_json().lower()
    )
    for forbidden in ("certified", "is compliant", "guaranteed compliant"):
        assert forbidden not in blob


# --------------------------------------------------------------------------- #
# Cross-surface: MCP authz parity
# --------------------------------------------------------------------------- #


def test_mcp_confirm_intake_denied_for_default_agent_role(tmp_path, monkeypatch) -> None:
    """The MCP confirm tool fails closed for the proposal-only default role."""
    import complyos.api.mcp_server as mcp_server

    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    db_path = str(tmp_path / "mcp.db")
    with pytest.raises(AuthorizationError) as exc:
        asyncio.run(mcp_server.confirm_intake_scope(request_id="x", db_path=db_path))
    assert exc.value.permission == "intake:confirm"


def test_mcp_submit_intake_allowed_for_default_agent_role(tmp_path, monkeypatch) -> None:
    """The MCP submit/draft tool is reachable by the proposal-only default role."""
    import complyos.api.mcp_server as mcp_server

    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    db_path = str(tmp_path / "mcp.db")
    result = asyncio.run(
        mcp_server.submit_intake(title="Agent ask", requester="agent", db_path=db_path)
    )
    assert result["request"]["status"] == "draft"
    assert result["packet"]["confirms_scope"] is False
    assert result["packet"]["requires_human_confirmation"] is True
