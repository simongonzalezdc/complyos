"""Source-intelligence review persistence for LocalRepository."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from complyos.core.repository_base import RepositoryBase
from complyos.core.repository_mappers import RepositoryMappers
from complyos.core.time import utc_now
from complyos.models.database import (
    DBSourceIntelJobExecution,
    DBSourceIntelProposal,
    DBSourceIntelRun,
    DBSourceIntelSchedule,
)
from complyos.source_intel.monitor import SourceMonitorRun


class SourceIntelRepositoryMixin(RepositoryBase, RepositoryMappers):
    """Source-intel runs, proposals, schedules, and job executions."""

    # ------------------------------------------------------------------
    # Source intelligence review persistence
    # ------------------------------------------------------------------
    def save_source_intel_run(
        self,
        *,
        tenant_id: str,
        query: str,
        run: SourceMonitorRun,
        created_by: str,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        run_id = str(uuid.uuid4())
        timestamp = created_at or utc_now()
        with self._session() as session:
            session.add(
                DBSourceIntelRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    query=query,
                    source_count=run.source_count,
                    snapshot_count=run.snapshot_count,
                    proposal_count=run.proposal_count,
                    coverage_gaps=run.coverage_gaps,
                    created_by=created_by,
                    created_at=timestamp,
                )
            )
            for proposal in run.proposals:
                payload = proposal.model_dump(mode="json")
                session.merge(
                    DBSourceIntelProposal(
                        id=proposal.id,
                        tenant_id=tenant_id,
                        run_id=run_id,
                        adapter_name=proposal.adapter_name,
                        signal_type=proposal.signal.signal_type,
                        source_id=proposal.signal.source_id,
                        source_url=proposal.source_url,
                        source_hash=proposal.source_hash,
                        approval_state=proposal.approval_state,
                        payload=payload,
                        created_at=timestamp,
                    )
                )
            session.commit()
        return {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "source_count": run.source_count,
            "snapshot_count": run.snapshot_count,
            "proposal_count": run.proposal_count,
            "coverage_gaps": run.coverage_gaps,
        }

    def list_source_intel_proposals(
        self,
        *,
        tenant_id: str,
        state: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBSourceIntelProposal).where(
                DBSourceIntelProposal.tenant_id == tenant_id
            )
            if state:
                query = query.where(DBSourceIntelProposal.approval_state == state)
            rows = query.order_by(DBSourceIntelProposal.created_at.desc()).limit(limit).all()
            return [self._to_source_intel_proposal_dict(row) for row in rows]

    def decide_source_intel_proposal(
        self,
        *,
        tenant_id: str,
        proposal_id: str,
        state: str,
        decided_by: str,
        decided_at: datetime | None = None,
    ) -> dict[str, Any]:
        with self._session() as session:
            proposal = (
                session.query(DBSourceIntelProposal)
                .where(
                    DBSourceIntelProposal.tenant_id == tenant_id,
                    DBSourceIntelProposal.id == proposal_id,
                )
                .first()
            )
            if proposal is None:
                raise ValueError(f"unknown source-intelligence proposal: {proposal_id}")
            proposal.approval_state = state
            proposal.decided_by = decided_by
            proposal.decided_at = decided_at or utc_now()
            payload = dict(proposal.payload or {})
            payload["approval_state"] = state
            proposal.payload = payload
            session.commit()
            session.refresh(proposal)
            return self._to_source_intel_proposal_dict(proposal)

    def save_source_intel_schedule(
        self,
        *,
        tenant_id: str,
        name: str,
        query: str,
        source_ids: list[str],
        interval_hours: int,
        mode: str,
        status: str,
        created_by: str,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = created_at or utc_now()
        with self._session() as session:
            schedule = (
                session.query(DBSourceIntelSchedule)
                .where(
                    DBSourceIntelSchedule.tenant_id == tenant_id,
                    DBSourceIntelSchedule.name == name,
                )
                .first()
            )
            if schedule is None:
                schedule = DBSourceIntelSchedule(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    name=name,
                    query=query,
                    source_ids=source_ids,
                    interval_hours=interval_hours,
                    mode=mode,
                    status=status,
                    created_by=created_by,
                    created_at=timestamp,
                )
                session.add(schedule)
            else:
                schedule.query = query
                schedule.source_ids = source_ids
                schedule.interval_hours = interval_hours
                schedule.mode = mode
                schedule.status = status
            session.commit()
            session.refresh(schedule)
            return self._to_source_intel_schedule_dict(schedule)

    def list_source_intel_schedules(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBSourceIntelSchedule).where(
                DBSourceIntelSchedule.tenant_id == tenant_id
            )
            if status:
                query = query.where(DBSourceIntelSchedule.status == status)
            rows = query.order_by(DBSourceIntelSchedule.created_at.desc()).limit(limit).all()
            return [self._to_source_intel_schedule_dict(row) for row in rows]

    def record_source_intel_job_execution(
        self,
        *,
        tenant_id: str,
        schedule_id: str,
        run_id: str | None,
        status: str,
        started_at: datetime,
        finished_at: datetime | None,
        summary: dict[str, Any],
        error: str | None,
        created_by: str,
    ) -> dict[str, Any]:
        with self._session() as session:
            schedule = (
                session.query(DBSourceIntelSchedule)
                .where(
                    DBSourceIntelSchedule.tenant_id == tenant_id,
                    DBSourceIntelSchedule.id == schedule_id,
                )
                .first()
            )
            if schedule is None:
                raise ValueError(f"unknown source-intelligence schedule: {schedule_id}")
            execution = DBSourceIntelJobExecution(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                schedule_id=schedule_id,
                run_id=run_id,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                summary=summary,
                error=error,
                created_by=created_by,
            )
            session.add(execution)
            if status == "succeeded":
                schedule.last_run_at = finished_at or started_at
            session.commit()
            session.refresh(execution)
            return self._to_source_intel_job_execution_dict(execution)

    def list_source_intel_job_executions(
        self,
        *,
        tenant_id: str,
        schedule_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBSourceIntelJobExecution).where(
                DBSourceIntelJobExecution.tenant_id == tenant_id
            )
            if schedule_id:
                query = query.where(DBSourceIntelJobExecution.schedule_id == schedule_id)
            rows = query.order_by(DBSourceIntelJobExecution.started_at.desc()).limit(limit).all()
            return [self._to_source_intel_job_execution_dict(row) for row in rows]

