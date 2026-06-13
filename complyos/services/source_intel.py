"""Service-layer source-intelligence review queue controls."""

from __future__ import annotations

from datetime import datetime, timedelta
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

VALID_JOB_STATUSES = frozenset({"succeeded", "failed", "skipped"})
VALID_SCHEDULE_MODES = frozenset({"fixture"})


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

    def create_schedule(
        self,
        context: ActorContext,
        *,
        name: str,
        query: str,
        interval_hours: int,
        source_ids: list[str] | None = None,
        mode: str = "fixture",
        status: str = "active",
    ) -> dict[str, Any]:
        """Create/update a tenant-scoped source-intelligence schedule."""
        require_permission(context, PERM_SOURCE_INTEL_RUN)
        if interval_hours < 1:
            raise ValueError("source-intelligence schedule interval must be at least 1 hour")
        if mode not in VALID_SCHEDULE_MODES:
            raise ValueError(f"unsupported source-intelligence schedule mode: {mode}")
        schedule = self.repository.save_source_intel_schedule(
            tenant_id=context.tenant_id,
            name=name,
            query=query,
            source_ids=source_ids or [],
            interval_hours=interval_hours,
            mode=mode,
            status=status,
            created_by=context.actor_id,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="source_intel.schedule.upsert",
            object_type="source_intel_schedule",
            object_id=str(schedule["id"]),
            result=status,
            request_id=context.request_id,
            metadata={
                "name": name,
                "query": query,
                "interval_hours": interval_hours,
                "mode": mode,
            },
        )
        return schedule

    def list_schedules(
        self,
        context: ActorContext,
        *,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tenant-scoped source-intelligence schedules."""
        require_permission(context, PERM_SOURCE_INTEL_READ)
        return self.repository.list_source_intel_schedules(
            tenant_id=context.tenant_id,
            status=status,
            limit=limit,
        )

    def due_schedules(
        self,
        context: ActorContext,
        *,
        now: datetime | None = None,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        """Return active schedules due for execution."""
        require_permission(context, PERM_SOURCE_INTEL_RUN)
        timestamp = now or datetime.utcnow()
        schedules = self.repository.list_source_intel_schedules(
            tenant_id=context.tenant_id,
            status="active",
            limit=500,
        )
        if force:
            return schedules

        due: list[dict[str, Any]] = []
        for schedule in schedules:
            last_run_at = schedule.get("last_run_at")
            if not isinstance(last_run_at, datetime):
                due.append(schedule)
                continue
            next_due_at = last_run_at + timedelta(hours=int(schedule["interval_hours"]))
            if next_due_at <= timestamp:
                due.append(schedule)
        return due

    def record_schedule_execution(
        self,
        context: ActorContext,
        *,
        schedule_id: str,
        run_id: str | None,
        status: str,
        started_at: datetime,
        finished_at: datetime | None,
        summary: dict[str, Any],
        error: str | None = None,
    ) -> dict[str, Any]:
        """Persist one scheduled-job execution row for observability."""
        require_permission(context, PERM_SOURCE_INTEL_RUN)
        if status not in VALID_JOB_STATUSES:
            raise ValueError(f"invalid source-intelligence job status: {status}")
        execution = self.repository.record_source_intel_job_execution(
            tenant_id=context.tenant_id,
            schedule_id=schedule_id,
            run_id=run_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            summary=summary,
            error=error,
            created_by=context.actor_id,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="source_intel.schedule.execute",
            object_type="source_intel_schedule",
            object_id=schedule_id,
            result=status,
            request_id=context.request_id,
            metadata={"run_id": run_id, "summary": summary, "error": error},
        )
        return execution

    def export_review_packet(
        self,
        context: ActorContext,
        *,
        proposal_limit: int = 500,
        action_limit: int = 100,
    ) -> dict[str, Any]:
        """Export review proposals, decisions, schedules, jobs, and audit actions."""
        require_permission(context, PERM_SOURCE_INTEL_READ)
        proposals = self.repository.list_source_intel_proposals(
            tenant_id=context.tenant_id,
            limit=proposal_limit,
        )
        schedules = self.repository.list_source_intel_schedules(
            tenant_id=context.tenant_id,
            limit=100,
        )
        executions = self.repository.list_source_intel_job_executions(
            tenant_id=context.tenant_id,
            limit=100,
        )
        decided_count = sum(
            1
            for proposal in proposals
            if proposal.get("decided_by") or proposal.get("approval_state") != "needs_review"
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="source_intel.review.export",
            object_type="source_intel_review_packet",
            object_id=None,
            result="exported",
            request_id=context.request_id,
            metadata={
                "proposal_count": len(proposals),
                "decided_count": decided_count,
            },
        )
        actions = self.repository.list_action_logs(
            tenant_id=context.tenant_id,
            limit=action_limit,
        )
        return {
            "tenant_id": context.tenant_id,
            "generated_at": datetime.utcnow().isoformat(),
            "proposal_count": len(proposals),
            "decided_count": decided_count,
            "proposals": proposals,
            "schedules": schedules,
            "job_executions": executions,
            "action_logs": actions,
        }
