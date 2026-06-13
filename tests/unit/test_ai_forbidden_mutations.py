"""Forbidden-mutation guards for the AI proposal layer (plan §11.2 / §13).

The AI layer is proposal-only. It must not expose any method that mutates
compliance state, and approving a proposal must not, by itself, change any
LearningRecord/import/rule/remediation state.
"""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import AIProposalService
from complyos.services.context import default_local_context

FORBIDDEN_METHODS = (
    "mark_compliant",
    "promote",
    "promote_import",
    "promote_batch",
    "execute_remediation",
    "run_remediation",
    "change_rules",
    "update_rules",
    "write_rules",
    "set_status",
    "mutate",
)


def test_ai_proposal_has_no_mark_compliant_method() -> None:
    assert not hasattr(AIProposalService, "mark_compliant")
    assert "mark_compliant" not in dir(AIProposalService)


def test_ai_proposal_cannot_promote_imports() -> None:
    for name in ("promote", "promote_import", "promote_batch"):
        assert not hasattr(AIProposalService, name), f"forbidden method exposed: {name}"


def test_ai_proposal_cannot_execute_remediation() -> None:
    for name in ("execute_remediation", "run_remediation", "remediate"):
        assert not hasattr(AIProposalService, name), f"forbidden method exposed: {name}"


def test_ai_proposal_cannot_change_rules() -> None:
    for name in ("change_rules", "update_rules", "write_rules", "set_rules"):
        assert not hasattr(AIProposalService, name), f"forbidden method exposed: {name}"


def test_ai_service_exposes_only_proposal_only_public_api() -> None:
    public = {name for name in dir(AIProposalService) if not name.startswith("_")}
    for forbidden in FORBIDDEN_METHODS:
        assert forbidden not in public, f"forbidden public method: {forbidden}"


def test_approval_does_not_mutate_compliance_state(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ai-no-mutation.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    proposal = service.propose_mapping(context, headers=["User ID", "Course ID", "Status"])
    approved = service.approve(context, proposal.proposal_id)

    # Approval only marks the proposal approved.
    assert approved.status == "APPROVED"
    # No compliance state appears as a side effect.
    assert repo.list_learning_records() == []
    assert repo.list_import_rows(proposal.proposal_id) == []
