"""AI proposal layer tests."""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import AIProposalService
from complyos.services.context import default_local_context


def test_ai_mapping_is_proposal_only_and_approvable(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ai.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    proposal = service.propose_mapping(context, headers=["User ID", "Course ID", "Status"])
    approved = service.approve(context, proposal.proposal_id)

    assert proposal.output["state_mutation_allowed"] is False
    assert proposal.output["suggested_mappings"]["User ID"] == "user_id"
    assert approved.status == "APPROVED"
    assert repo.list_learning_records() == []
