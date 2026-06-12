"""Service-layer source-intelligence review queue controls."""

from __future__ import annotations

from typing import Any

from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_SOURCE_INTEL_DECIDE,
    PERM_SOURCE_INTEL_READ,
    PERM_SOURCE_INTEL_RUN,
    ActorContext,
    require_permission,
)
from complyos.source_intel.monitor import SourceMonitorRun

VALID_REVIEW_STATES = frozenset(
    {
        "needs_review",
        "under_review",
        "approved_for_brief",
        "approved_for_rule_proposal",
        "approved_for_microlearn",
        "rejected",
        "superseded",
    }
)


class SourceIntelService:
    """Persist and decide source-intelligence proposals with RBAC and tenant scope."""

    def __init__(self, repository: LocalRepository) -> None:
        self.repository = repository

    def record_run(
        self,
        context: ActorContext,
        *,
        query: str,
        run: SourceMonitorRun,
    ) -> dict[str, Any]:
        """Persist a source-intelligence run and its generated proposals."""
        require_permission(context, PERM_SOURCE_INTEL_RUN)
        receipt = self.repository.save_source_intel_run(
            tenant_id=context.tenant_id,
            query=query,
            run=run,
            created_by=context.actor_id,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="source_intel.run.record",
            object_type="source_intel_run",
            object_id=str(receipt["run_id"]),
            result="recorded",
            request_id=context.request_id,
            metadata={
                "query": query,
                "proposal_count": receipt["proposal_count"],
                "snapshot_count": receipt["snapshot_count"],
            },
        )
        return receipt

    def list_proposals(
        self,
        context: ActorContext,
        *,
        state: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List review proposals visible to the current tenant."""
        require_permission(context, PERM_SOURCE_INTEL_READ)
        return self.repository.list_source_intel_proposals(
            tenant_id=context.tenant_id,
            state=state,
            limit=limit,
        )

    def decide_proposal(
        self,
        context: ActorContext,
        *,
        proposal_id: str,
        state: str,
    ) -> dict[str, Any]:
        """Approve/reject/supersede a proposal without mutating rules or training."""
        require_permission(context, PERM_SOURCE_INTEL_DECIDE)
        if state not in VALID_REVIEW_STATES:
            raise ValueError(f"invalid source-intelligence review state: {state}")
        proposal = self.repository.decide_source_intel_proposal(
            tenant_id=context.tenant_id,
            proposal_id=proposal_id,
            state=state,
            decided_by=context.actor_id,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="source_intel.proposal.decide",
            object_type="source_intel_proposal",
            object_id=proposal_id,
            result=state,
            request_id=context.request_id,
            metadata={"state": state, "signal_type": proposal.get("signal_type")},
        )
        return proposal
