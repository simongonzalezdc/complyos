"""AI proposal reject + expiry lifecycle tests (plan §11.3).

Status flows: PROPOSED -> APPROVED | REJECTED | EXPIRED. A rejected proposal
cannot be approved. A proposal older than the TTL cannot be approved (computed
at approval time, no background job required).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import (
    DEFAULT_AI_PROPOSAL_TTL_HOURS,
    AIProposalExpiredError,
    AIProposalService,
)
from complyos.services.context import default_local_context


def test_propose_reject_then_cannot_approve(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ai-reject.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    proposal = service.propose_mapping(context, headers=["User ID", "Course ID"])
    rejected = service.reject(context, proposal.proposal_id, reason="not useful")

    assert rejected.status == "REJECTED"

    stored = repo.get_ai_proposal(proposal.proposal_id)
    assert stored is not None
    assert stored["status"] == "REJECTED"

    # A reject action is recorded in the action log with the reason.
    logs = repo.list_action_logs(tenant_id=context.tenant_id)
    reject_logs = [item for item in logs if item["action"] == "ai.proposal.reject"]
    assert reject_logs, "reject must write an action-log entry"
    assert reject_logs[0]["object_id"] == proposal.proposal_id

    # Once rejected, it can never be approved.
    with pytest.raises(ValueError):
        service.approve(context, proposal.proposal_id)


def test_reject_requires_ai_approve_permission(tmp_path) -> None:
    from complyos.services.context import AuthorizationError

    repo = LocalRepository(str(tmp_path / "ai-reject-perm.db"))
    service = AIProposalService(repo)
    proposer = default_local_context(surface="cli", role="agent_service_account")

    proposal = service.propose_mapping(proposer, headers=["User ID"])

    # agent_service_account has ai:propose but NOT ai:approve.
    with pytest.raises(AuthorizationError):
        service.reject(proposer, proposal.proposal_id, reason="nope")


def test_expired_proposal_cannot_be_approved(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ai-expired.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    proposal = service.propose_mapping(context, headers=["User ID", "Course ID"])

    # Backdate the proposal past the TTL.
    stale = datetime.now(UTC) - timedelta(hours=DEFAULT_AI_PROPOSAL_TTL_HOURS + 1)
    repo.update_ai_proposal_created_at(proposal.proposal_id, stale)

    with pytest.raises(AIProposalExpiredError):
        service.approve(context, proposal.proposal_id)


def test_proposal_within_ttl_can_be_approved(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ai-fresh.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    proposal = service.propose_mapping(context, headers=["User ID", "Course ID"])
    approved = service.approve(context, proposal.proposal_id)

    assert approved.status == "APPROVED"


def test_ttl_is_configurable_via_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("COMPLYOS_AI_PROPOSAL_TTL_HOURS", "1")
    repo = LocalRepository(str(tmp_path / "ai-env-ttl.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    proposal = service.propose_mapping(context, headers=["User ID"])
    stale = datetime.now(UTC) - timedelta(hours=2)
    repo.update_ai_proposal_created_at(proposal.proposal_id, stale)

    with pytest.raises(AIProposalExpiredError):
        service.approve(context, proposal.proposal_id)
