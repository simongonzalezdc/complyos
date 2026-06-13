"""Repository layer for persisting domain models to SQLite."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from complyos.core.repository_mappers import RepositoryMappers
from complyos.core.time import utc_now
from complyos.models.database import (
    DBAIProposal,
    DBAIProvenance,
    DBApproval,
    DBAuditActionLog,
    DBAuditSnapshot,
    DBCourse,
    DBEnrollment,
    DBEvidenceLedger,
    DBImportBatch,
    DBImportDecision,
    DBImportRow,
    DBInboundWebhookEvent,
    DBLearningRecord,
    DBLegalHold,
    DBNotificationDelivery,
    DBNotificationEvent,
    DBNotificationPreference,
    DBPrivacyRequest,
    DBRetentionPolicy,
    DBSourceIntelJobExecution,
    DBSourceIntelProposal,
    DBSourceIntelRun,
    DBSourceIntelSchedule,
    DBUser,
    init_db,
)
from complyos.models.domain import Course, Enrollment, LearningRecord, LearningRecordStatus, User
from complyos.source_intel.monitor import SourceMonitorRun

# Legal-hold scopes that suspend deletion across an entire tenant (not a single
# subject). Both "tenant" and "system" holds must block every retention dataset.
_TENANT_WIDE_HOLD_SCOPES = ("tenant", "system")


@dataclass(frozen=True)
class HoldDecision:
    """Single source of truth for which records an active legal hold protects.

    Centralizing this prevents the per-query drift that let subject- and
    system-scoped holds be silently ignored by most retention-eligibility
    checks (a spoliation risk for a compliance product).
    """

    tenant_blocked: bool
    held_subject_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def any_active(self) -> bool:
        """True when any active hold exists (tenant/system-wide or per-subject)."""
        return self.tenant_blocked or bool(self.held_subject_ids)


class LocalRepository(RepositoryMappers):
    """CRUD operations backed by local SQLite via SQLAlchemy."""

    def __init__(self, db_path: str = "complyos.db", database_url: str | None = None) -> None:
        self._sessionmaker = init_db(database_url or db_path)

    def _session(self) -> Session:
        return self._sessionmaker()

    @staticmethod
    def _owner_tenant_id(session: Session, user_id: str) -> str:
        """Tenant a learner/item record inherits from its owning user.

        Learning records and enrollments share their learner's tenant so DSR
        export/delete can scope them precisely. Falls back to the default tenant
        only when the learner has not been synced locally (e.g. standalone
        import before an HR sync), matching the column default.
        """
        # no_autoflush: resolving the owner must not flush the half-built record
        # currently pending in the session (its required columns aren't set yet).
        with session.no_autoflush:
            owner = session.get(DBUser, user_id)
        return owner.tenant_id if owner is not None else "local-default"

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------
    def save_user(self, user: User) -> None:
        with self._session() as session:
            db_user = session.get(DBUser, user.id)
            if db_user is None:
                db_user = DBUser(id=user.id)
                session.add(db_user)

            db_user.employee_id = user.employee_id
            db_user.email = user.email
            db_user.first_name = user.first_name
            db_user.last_name = user.last_name
            db_user.department = user.department
            db_user.region = user.region or ""
            db_user.hire_date = user.hire_date
            db_user.employment_status = user.employment_status.value
            db_user.manager_id = user.manager_id
            db_user.custom_attributes = user.custom_attributes
            db_user.tenant_id = (user.custom_attributes or {}).get("tenant_id", "local-default")
            session.commit()

    def get_user(self, user_id: str) -> User | None:
        with self._session() as session:
            db = session.get(DBUser, user_id)
            if db is None:
                return None
            return self._to_user(db)

    def list_users(
        self,
        *,
        department: str | None = None,
        region: str | None = None,
        employment_status: str | None = None,
    ) -> list[User]:
        with self._session() as session:
            query = session.query(DBUser)
            if department:
                query = query.where(DBUser.department == department)
            if region:
                query = query.where(DBUser.region == region)
            if employment_status:
                query = query.where(DBUser.employment_status == employment_status)
            return [self._to_user(u) for u in query.all()]

    # ------------------------------------------------------------------
    # Courses
    # ------------------------------------------------------------------
    def save_course(self, course: Course) -> None:
        with self._session() as session:
            db_course = session.get(DBCourse, course.id)
            if db_course is None:
                db_course = DBCourse(id=course.id)
                session.add(db_course)

            db_course.code = course.code
            db_course.title = course.title
            db_course.description = course.description
            db_course.duration_minutes = course.duration_minutes
            db_course.mandatory = course.mandatory
            db_course.category = course.category
            session.commit()

    def get_course(self, course_id: str) -> Course | None:
        with self._session() as session:
            db = session.get(DBCourse, course_id)
            if db is None:
                return None
            return self._to_course(db)

    def list_courses(self, *, mandatory: bool | None = None) -> list[Course]:
        with self._session() as session:
            query = session.query(DBCourse)
            if mandatory is not None:
                query = query.where(DBCourse.mandatory == mandatory)
            return [self._to_course(c) for c in query.all()]

    # ------------------------------------------------------------------
    # Enrollments
    # ------------------------------------------------------------------
    def save_enrollment(self, enrollment: Enrollment) -> None:
        with self._session() as session:
            db_enrollment = session.get(DBEnrollment, enrollment.id)
            if db_enrollment is None:
                db_enrollment = DBEnrollment(id=enrollment.id)
                session.add(db_enrollment)

            db_enrollment.user_id = enrollment.user_id
            db_enrollment.course_id = enrollment.course_id
            db_enrollment.tenant_id = self._owner_tenant_id(session, enrollment.user_id)
            db_enrollment.status = enrollment.status.value
            db_enrollment.assigned_date = enrollment.assigned_date
            db_enrollment.due_date = enrollment.due_date
            db_enrollment.completed_date = enrollment.completed_date
            db_enrollment.completion_percentage = enrollment.completion_percentage or 0.0
            db_enrollment.score = enrollment.score
            session.commit()

    def list_enrollments(
        self,
        *,
        user_id: str | None = None,
        course_id: str | None = None,
        status: str | None = None,
    ) -> list[Enrollment]:
        with self._session() as session:
            query = session.query(DBEnrollment)
            if user_id:
                query = query.where(DBEnrollment.user_id == user_id)
            if course_id:
                query = query.where(DBEnrollment.course_id == course_id)
            if status:
                query = query.where(DBEnrollment.status == status)
            return [self._to_enrollment(e) for e in query.all()]

    # ------------------------------------------------------------------
    # Learning records
    # ------------------------------------------------------------------
    def save_learning_record(self, record: LearningRecord) -> None:
        with self._session() as session:
            db_record = session.get(DBLearningRecord, record.id)
            if db_record is None:
                db_record = DBLearningRecord(id=record.id)
                session.add(db_record)

            db_record.user_id = record.user_id
            db_record.course_id = record.course_id
            db_record.tenant_id = self._owner_tenant_id(session, record.user_id)
            db_record.source_system = record.source_system
            db_record.source_record_id = record.source_record_id
            db_record.status = record.status.value
            db_record.assigned_date = record.assigned_date
            db_record.due_date = record.due_date
            db_record.completed_date = record.completed_date
            db_record.completion_percentage = record.completion_percentage
            db_record.score = record.score
            db_record.exempt = record.exempt
            db_record.expires_at = record.expires_at
            db_record.raw_source_hash = record.raw_source_hash
            db_record.source_payload = record.source_payload
            session.commit()

    def promote_import_learning_records(
        self,
        *,
        batch_id: str,
        row_record_pairs: list[tuple[str, LearningRecord]],
        promoted_by: str,
        promoted_at: datetime,
        evidence_entry: dict[str, Any],
    ) -> str:
        """Promote import rows, active records, batch state, and evidence atomically."""
        evidence_id = str(uuid.uuid4())
        with self._session() as session:
            try:
                batch = session.get(DBImportBatch, batch_id)
                if batch is None:
                    raise ValueError(f"unknown import batch during promotion: {batch_id}")
                for row_id, record in row_record_pairs:
                    db_record = session.get(DBLearningRecord, record.id)
                    if db_record is None:
                        db_record = DBLearningRecord(id=record.id)
                        session.add(db_record)

                    db_record.user_id = record.user_id
                    db_record.course_id = record.course_id
                    # Promoted records carry the batch's tenant so DSR scoping
                    # holds even when the learner was never separately synced.
                    db_record.tenant_id = batch.tenant_id
                    db_record.source_system = record.source_system
                    db_record.source_record_id = record.source_record_id
                    db_record.status = record.status.value
                    db_record.assigned_date = record.assigned_date
                    db_record.due_date = record.due_date
                    db_record.completed_date = record.completed_date
                    db_record.completion_percentage = record.completion_percentage
                    db_record.score = record.score
                    db_record.exempt = record.exempt
                    db_record.expires_at = record.expires_at
                    db_record.raw_source_hash = record.raw_source_hash
                    db_record.source_payload = record.source_payload

                    row = (
                        session.query(DBImportRow)
                        .where(DBImportRow.batch_id == batch_id, DBImportRow.id == row_id)
                        .first()
                    )
                    if row is None:
                        raise ValueError(f"unknown import row during promotion: {row_id}")
                    row.validation_status = "PROMOTED"

                batch.status = "PROMOTED"
                batch.promoted_by = promoted_by
                batch.promoted_at = promoted_at

                session.add(
                    DBEvidenceLedger(
                        id=evidence_id,
                        tenant_id=batch.tenant_id,
                        timestamp=evidence_entry["timestamp"],
                        query_type=evidence_entry["query_type"],
                        query_params=json.dumps(
                            evidence_entry["query_params"],
                            sort_keys=True,
                        ),
                        raw_data_hash=evidence_entry["raw_data_hash"],
                        transformation_steps=json.dumps(evidence_entry["transformation_steps"]),
                        output_hash=evidence_entry["output_hash"],
                        output_summary=evidence_entry["output_summary"],
                    )
                )
                session.commit()
            except Exception:
                session.rollback()
                raise
        return evidence_id

    def list_learning_records(
        self,
        *,
        user_id: str | None = None,
        course_id: str | None = None,
        status: str | LearningRecordStatus | None = None,
        source_system: str | None = None,
    ) -> list[LearningRecord]:
        with self._session() as session:
            query = session.query(DBLearningRecord)
            if user_id:
                query = query.where(DBLearningRecord.user_id == user_id)
            if course_id:
                query = query.where(DBLearningRecord.course_id == course_id)
            if status:
                status_value = status.value if isinstance(status, LearningRecordStatus) else status
                query = query.where(DBLearningRecord.status == status_value)
            if source_system:
                query = query.where(DBLearningRecord.source_system == source_system)
            return [self._to_learning_record(r) for r in query.all()]

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------
    def sync_users(self, users: list[User]) -> int:
        for user in users:
            self.save_user(user)
        return len(users)

    def sync_courses(self, courses: list[Course]) -> int:
        for course in courses:
            self.save_course(course)
        return len(courses)

    def sync_enrollments(self, enrollments: list[Enrollment]) -> int:
        for enrollment in enrollments:
            self.save_enrollment(enrollment)
        return len(enrollments)

    def sync_learning_records(self, records: list[LearningRecord]) -> int:
        for record in records:
            self.save_learning_record(record)
        return len(records)

    # ------------------------------------------------------------------
    # Audit snapshots
    # ------------------------------------------------------------------
    def save_audit_snapshot(
        self,
        *,
        scope: str,
        generated_at: datetime,
        gaps_found: int,
        gaps: list[dict[str, Any]],
        gaps_by_severity: dict[str, int],
        evidence_hash: str,
    ) -> str:
        with self._session() as session:
            snapshot = DBAuditSnapshot(
                id=str(uuid.uuid4()),
                generated_at=generated_at,
                scope=scope,
                gaps_found=gaps_found,
                gaps=gaps,
                gaps_by_severity=gaps_by_severity,
                evidence_hash=evidence_hash,
            )
            session.add(snapshot)
            session.commit()
            return snapshot.id

    def get_latest_audit_snapshot(self, scope: str) -> dict[str, Any] | None:
        with self._session() as session:
            snapshot = (
                session.query(DBAuditSnapshot)
                .where(DBAuditSnapshot.scope == scope)
                .order_by(DBAuditSnapshot.generated_at.desc())
                .first()
            )
            if snapshot is None:
                return None
            return self._to_snapshot_dict(snapshot)

    def list_audit_snapshots(
        self, scope: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBAuditSnapshot)
            if scope:
                query = query.where(DBAuditSnapshot.scope == scope)
            query = query.order_by(DBAuditSnapshot.generated_at.desc()).limit(limit)
            return [self._to_snapshot_dict(s) for s in query.all()]

    # ------------------------------------------------------------------
    # Evidence ledger + action log
    # ------------------------------------------------------------------
    def append_evidence_entry(
        self,
        *,
        tenant_id: str = "local-default",
        query_type: str,
        query_params: dict[str, Any],
        raw_data_hash: str,
        transformation_steps: list[str],
        output_hash: str,
        output_summary: str,
        timestamp: datetime | None = None,
    ) -> str:
        entry_id = str(uuid.uuid4())
        with self._session() as session:
            session.add(
                DBEvidenceLedger(
                    id=entry_id,
                    tenant_id=tenant_id,
                    timestamp=timestamp or utc_now(),
                    query_type=query_type,
                    query_params=json.dumps(query_params, sort_keys=True),
                    raw_data_hash=raw_data_hash,
                    transformation_steps=json.dumps(transformation_steps),
                    output_hash=output_hash,
                    output_summary=output_summary,
                )
            )
            session.commit()
        return entry_id

    def list_evidence_ledger(
        self,
        *,
        tenant_id: str | None = "local-default",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBEvidenceLedger)
            if tenant_id is not None:
                query = query.where(DBEvidenceLedger.tenant_id == tenant_id)
            rows = query.order_by(DBEvidenceLedger.timestamp.desc()).limit(limit).all()
            return [self._to_evidence_dict(row) for row in rows]

    def save_action_log(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        surface: str,
        action: str,
        object_type: str,
        object_id: str | None,
        result: str,
        request_id: str | None,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> str:
        log_id = str(uuid.uuid4())
        with self._session() as session:
            session.add(
                DBAuditActionLog(
                    id=log_id,
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    surface=surface,
                    action=action,
                    object_type=object_type,
                    object_id=object_id,
                    result=result,
                    request_id=request_id,
                    redacted_metadata=metadata or {},
                    created_at=created_at or utc_now(),
                )
            )
            session.commit()
        return log_id

    def list_action_logs(
        self, *, tenant_id: str = "local-default", limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(DBAuditActionLog)
                .where(DBAuditActionLog.tenant_id == tenant_id)
                .order_by(DBAuditActionLog.created_at.desc())
                .limit(limit)
                .all()
            )
            return [self._to_action_log_dict(row) for row in rows]

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

    # ------------------------------------------------------------------
    # Notification outbox persistence
    # ------------------------------------------------------------------
    def save_notification_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source: str,
        object_type: str,
        object_id: str | None,
        payload: dict[str, Any],
        payload_hash: str,
        channels: list[str],
        created_by: str,
        status: str = "queued",
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        timestamp = created_at or utc_now()
        with self._session() as session:
            event = DBNotificationEvent(
                id=event_id,
                tenant_id=tenant_id,
                event_type=event_type,
                source=source,
                object_type=object_type,
                object_id=object_id,
                payload=payload,
                payload_hash=payload_hash,
                status=status,
                created_by=created_by,
                created_at=timestamp,
            )
            session.add(event)
            for channel in channels:
                session.add(
                    DBNotificationDelivery(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        event_id=event_id,
                        channel=channel,
                        destination_ref=channel,
                        status="pending",
                        attempts=0,
                        max_attempts=3,
                        response_metadata={},
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
            session.commit()
            session.refresh(event)
            return self._to_notification_event_dict(event, delivery_count=len(channels))

    def save_notification_preference(
        self,
        *,
        tenant_id: str,
        channel: str,
        event_type: str,
        enabled: bool,
        reason: str | None,
        updated_by: str,
        updated_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = updated_at or utc_now()
        with self._session() as session:
            preference = (
                session.query(DBNotificationPreference)
                .where(
                    DBNotificationPreference.tenant_id == tenant_id,
                    DBNotificationPreference.channel == channel,
                    DBNotificationPreference.event_type == event_type,
                )
                .first()
            )
            if preference is None:
                preference = DBNotificationPreference(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    channel=channel,
                    event_type=event_type,
                    enabled=enabled,
                    reason=reason,
                    updated_by=updated_by,
                    updated_at=timestamp,
                )
                session.add(preference)
            else:
                preference.enabled = enabled
                preference.reason = reason
                preference.updated_by = updated_by
                preference.updated_at = timestamp
            session.commit()
            session.refresh(preference)
            return self._to_notification_preference_dict(preference)

    def list_notification_preferences(self, *, tenant_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(DBNotificationPreference)
                .where(DBNotificationPreference.tenant_id == tenant_id)
                .order_by(
                    DBNotificationPreference.event_type.asc(),
                    DBNotificationPreference.channel.asc(),
                )
                .all()
            )
            return [self._to_notification_preference_dict(row) for row in rows]

    def save_inbound_webhook_event(
        self,
        *,
        tenant_id: str,
        source: str,
        event_type: str,
        object_type: str,
        object_id: str | None,
        payload: dict[str, Any],
        payload_hash: str,
        signature_valid: bool,
        status: str,
        header_metadata: dict[str, Any],
        received_by: str,
        received_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = received_at or utc_now()
        with self._session() as session:
            event = DBInboundWebhookEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                source=source,
                event_type=event_type,
                object_type=object_type,
                object_id=object_id,
                payload=payload,
                payload_hash=payload_hash,
                signature_valid=signature_valid,
                status=status,
                header_metadata=header_metadata,
                received_by=received_by,
                received_at=timestamp,
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            return self._to_inbound_webhook_event_dict(event)

    def list_inbound_webhook_events(
        self,
        *,
        tenant_id: str,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBInboundWebhookEvent).where(
                DBInboundWebhookEvent.tenant_id == tenant_id
            )
            if source:
                query = query.where(DBInboundWebhookEvent.source == source)
            rows = query.order_by(DBInboundWebhookEvent.received_at.desc()).limit(limit).all()
            return [self._to_inbound_webhook_event_dict(row) for row in rows]

    def list_notification_deliveries(
        self,
        *,
        tenant_id: str,
        status: str | None = "pending",
        limit: int = 50,
        due_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBNotificationDelivery).where(
                DBNotificationDelivery.tenant_id == tenant_id
            )
            if status:
                query = query.where(DBNotificationDelivery.status == status)
            if due_at is not None:
                # Honor the retry backoff: a delivery that failed and was scheduled
                # for a future retry must not be re-attempted until it is due. Rows
                # never attempted (next_attempt_at IS NULL) are always due.
                query = query.where(
                    DBNotificationDelivery.next_attempt_at.is_(None)
                    | (DBNotificationDelivery.next_attempt_at <= due_at)
                )
            rows = query.order_by(DBNotificationDelivery.created_at.asc()).limit(limit).all()
            deliveries: list[dict[str, Any]] = []
            for row in rows:
                event = session.get(DBNotificationEvent, row.event_id)
                deliveries.append(self._to_notification_delivery_dict(row, event))
            return deliveries

    def get_notification_delivery(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
    ) -> dict[str, Any] | None:
        """Point lookup of one tenant-scoped delivery (avoids a bounded list scan)."""
        with self._session() as session:
            delivery = (
                session.query(DBNotificationDelivery)
                .where(
                    DBNotificationDelivery.tenant_id == tenant_id,
                    DBNotificationDelivery.id == delivery_id,
                )
                .first()
            )
            if delivery is None:
                return None
            event = session.get(DBNotificationEvent, delivery.event_id)
            return self._to_notification_delivery_dict(delivery, event)

    def mark_notification_delivery(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
        status: str,
        increment_attempts: bool,
        response_metadata: dict[str, Any] | None = None,
        error: str | None = None,
        next_attempt_at: datetime | None = None,
        sent_at: datetime | None = None,
    ) -> dict[str, Any]:
        with self._session() as session:
            delivery = (
                session.query(DBNotificationDelivery)
                .where(
                    DBNotificationDelivery.tenant_id == tenant_id,
                    DBNotificationDelivery.id == delivery_id,
                )
                .first()
            )
            if delivery is None:
                raise ValueError(f"unknown notification delivery: {delivery_id}")
            if increment_attempts:
                delivery.attempts += 1
            delivery.status = status
            delivery.response_metadata = response_metadata or {}
            delivery.last_error = error
            delivery.next_attempt_at = next_attempt_at
            delivery.sent_at = sent_at
            delivery.updated_at = utc_now()
            session.commit()
            session.refresh(delivery)
            event = session.get(DBNotificationEvent, delivery.event_id)
            return self._to_notification_delivery_dict(delivery, event)

    @staticmethod
    def _to_snapshot_dict(snapshot: DBAuditSnapshot) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "generated_at": snapshot.generated_at,
            "scope": snapshot.scope,
            "gaps_found": snapshot.gaps_found,
            "gaps": snapshot.gaps or [],
            "gaps_by_severity": snapshot.gaps_by_severity or {},
            "evidence_hash": snapshot.evidence_hash,
        }

    # ------------------------------------------------------------------
    # Import lifecycle
    # ------------------------------------------------------------------
    def save_import_batch(self, batch: dict[str, Any]) -> None:
        with self._session() as session:
            db_batch = DBImportBatch(
                id=batch["id"],
                tenant_id=batch["tenant_id"],
                source_system=batch["source_system"],
                profile=batch["profile"],
                raw_file_hash=batch["raw_file_hash"],
                status=batch["status"],
                idempotency_key=batch["idempotency_key"],
                created_by=batch["created_by"],
                created_at=batch.get("created_at") or utc_now(),
                batch_metadata=batch.get("metadata") or {},
            )
            session.add(db_batch)
            session.commit()

    def get_import_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            batch = session.get(DBImportBatch, batch_id)
            return self._to_import_batch_dict(batch) if batch else None

    def get_import_batch_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self._session() as session:
            batch = (
                session.query(DBImportBatch)
                .where(
                    DBImportBatch.tenant_id == tenant_id,
                    DBImportBatch.idempotency_key == idempotency_key,
                )
                .first()
            )
            return self._to_import_batch_dict(batch) if batch else None

    def update_import_batch_status(
        self,
        batch_id: str,
        status: str,
        *,
        promoted_by: str | None = None,
        promoted_at: datetime | None = None,
    ) -> None:
        with self._session() as session:
            batch = session.get(DBImportBatch, batch_id)
            if batch is None:
                return
            batch.status = status
            if promoted_by is not None:
                batch.promoted_by = promoted_by
            if promoted_at is not None:
                batch.promoted_at = promoted_at
            session.commit()

    def save_import_rows(self, batch_id: str, rows: list[dict[str, Any]]) -> None:
        with self._session() as session:
            for row in rows:
                session.add(
                    DBImportRow(
                        id=row["id"],
                        batch_id=batch_id,
                        row_number=row["row_number"],
                        normalized_payload=row["normalized_payload"],
                        raw_payload_hash=row["raw_payload_hash"],
                        validation_status=row["validation_status"],
                        rejection_codes=row.get("rejection_codes") or [],
                        source_record_id=row.get("source_record_id"),
                        issues=row.get("issues") or [],
                    )
                )
            session.commit()

    def list_import_rows(self, batch_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(DBImportRow)
                .where(DBImportRow.batch_id == batch_id)
                .order_by(DBImportRow.row_number)
                .all()
            )
            return [self._to_import_row_dict(row) for row in rows]

    def update_import_row_status(self, batch_id: str, row_id: str, status: str) -> None:
        with self._session() as session:
            row = (
                session.query(DBImportRow)
                .where(DBImportRow.batch_id == batch_id, DBImportRow.id == row_id)
                .first()
            )
            if row is None:
                return
            row.validation_status = status
            session.commit()

    def save_import_decision(self, decision: dict[str, Any]) -> None:
        with self._session() as session:
            session.add(
                DBImportDecision(
                    id=decision["id"],
                    batch_id=decision["batch_id"],
                    row_id=decision["row_id"],
                    decision_type=decision["decision_type"],
                    decision_payload=decision.get("decision_payload") or {},
                    decided_by=decision["decided_by"],
                    decided_at=decision.get("decided_at") or utc_now(),
                    reason=decision.get("reason"),
                )
            )
            session.commit()

    def list_import_decisions(self, batch_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(DBImportDecision)
                .where(DBImportDecision.batch_id == batch_id)
                .order_by(DBImportDecision.decided_at.desc())
                .all()
            )
            return [self._to_import_decision_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # AI proposals
    # ------------------------------------------------------------------
    def save_ai_proposal(self, proposal: dict[str, Any]) -> None:
        provenance = proposal.get("provenance") or {}
        with self._session() as session:
            session.add(
                DBAIProposal(
                    id=proposal["id"],
                    tenant_id=proposal["tenant_id"],
                    proposal_type=proposal["proposal_type"],
                    input_hash=proposal["input_hash"],
                    output_hash=proposal["output_hash"],
                    status=proposal["status"],
                    created_by=proposal["created_by"],
                    created_at=proposal.get("created_at") or utc_now(),
                    output=proposal.get("output") or {},
                )
            )
            session.add(
                DBAIProvenance(
                    proposal_id=proposal["id"],
                    model_provider=provenance.get("model_provider", "unknown"),
                    model_name=provenance.get("model_name", "unknown"),
                    prompt_hash=provenance.get("prompt_hash", ""),
                    redaction_policy=provenance.get("redaction_policy", "unknown"),
                    response_hash=provenance.get("response_hash", proposal["output_hash"]),
                    usage_metadata=provenance,
                )
            )
            session.commit()

    def get_ai_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            proposal = session.get(DBAIProposal, proposal_id)
            if proposal is None:
                return None
            provenance = session.get(DBAIProvenance, proposal_id)
            return self._to_ai_proposal_dict(proposal, provenance)

    def update_ai_proposal_status(
        self,
        proposal_id: str,
        status: str,
        *,
        approved_by: str | None = None,
        approved_at: datetime | None = None,
    ) -> None:
        with self._session() as session:
            proposal = session.get(DBAIProposal, proposal_id)
            if proposal is None:
                return
            proposal.status = status
            if approved_by is not None:
                proposal.approved_by = approved_by
            if approved_at is not None:
                proposal.approved_at = approved_at
            session.commit()

    # ------------------------------------------------------------------
    # Privacy program workflows
    # ------------------------------------------------------------------
    def save_privacy_request(self, request: dict[str, Any]) -> None:
        with self._session() as session:
            session.add(
                DBPrivacyRequest(
                    id=request["id"],
                    tenant_id=request["tenant_id"],
                    subject_id=request["subject_id"],
                    request_type=request["request_type"],
                    status=request.get("status", "OPEN"),
                    region=request.get("region"),
                    opened_by=request["opened_by"],
                    created_at=request.get("created_at") or utc_now(),
                    request_metadata=request.get("metadata") or {},
                    result_summary=request.get("result_summary") or {},
                )
            )
            session.commit()

    def get_privacy_request(self, request_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            request = session.get(DBPrivacyRequest, request_id)
            return self._to_privacy_request_dict(request) if request else None

    def update_privacy_request_status(
        self,
        request_id: str,
        status: str,
        *,
        closed_by: str | None = None,
        completed_at: datetime | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        with self._session() as session:
            request = session.get(DBPrivacyRequest, request_id)
            if request is None:
                return
            request.status = status
            if closed_by is not None:
                request.closed_by = closed_by
            if completed_at is not None:
                request.completed_at = completed_at
            if result_summary is not None:
                request.result_summary = result_summary
            session.commit()

    def save_approval(self, approval: dict[str, Any]) -> str:
        approval_id = approval.get("id") or str(uuid.uuid4())
        with self._session() as session:
            session.add(
                DBApproval(
                    id=approval_id,
                    tenant_id=approval["tenant_id"],
                    object_type=approval["object_type"],
                    object_id=approval["object_id"],
                    approval_type=approval["approval_type"],
                    approved_by=approval.get("approved_by"),
                    status=approval.get("status", "approved"),
                    created_at=approval.get("created_at") or utc_now(),
                )
            )
            session.commit()
        return approval_id

    def get_subject_export(self, subject_id: str, *, tenant_id: str) -> dict[str, Any]:
        with self._session() as session:
            # Tenant scoping is a real, indexed column on every PII table — no
            # fallback. A subject (and their records) is only visible to the
            # tenant that owns them, so one tenant cannot export another's data.
            user = session.get(DBUser, subject_id)
            if user is not None and user.tenant_id != tenant_id:
                user = None
            learning_records = (
                session.query(DBLearningRecord)
                .where(
                    DBLearningRecord.user_id == subject_id,
                    DBLearningRecord.tenant_id == tenant_id,
                )
                .all()
                if user is not None
                else []
            )
            enrollments = (
                session.query(DBEnrollment)
                .where(
                    DBEnrollment.user_id == subject_id,
                    DBEnrollment.tenant_id == tenant_id,
                )
                .all()
                if user is not None
                else []
            )
            return {
                "subject": self._to_user(user).model_dump(mode="json") if user else {},
                "learning_records": [
                    self._to_learning_record(record).model_dump(mode="json")
                    for record in learning_records
                ],
                "enrollments": [
                    self._to_enrollment(enrollment).model_dump(mode="json")
                    for enrollment in enrollments
                ],
            }

    def delete_subject_records(self, subject_id: str, *, tenant_id: str) -> dict[str, int]:
        with self._session() as session:
            # Erasure is tenant-scoped on the indexed tenant_id column: a caller
            # can only delete a subject and the records owned by their own tenant.
            user = session.get(DBUser, subject_id)
            if user is None or user.tenant_id != tenant_id:
                return {"users": 0, "learning_records": 0, "enrollments": 0}

            learning_records = (
                session.query(DBLearningRecord)
                .where(
                    DBLearningRecord.user_id == subject_id,
                    DBLearningRecord.tenant_id == tenant_id,
                )
                .delete(synchronize_session=False)
            )
            enrollments = (
                session.query(DBEnrollment)
                .where(
                    DBEnrollment.user_id == subject_id,
                    DBEnrollment.tenant_id == tenant_id,
                )
                .delete(synchronize_session=False)
            )
            # Complete the erasure: the subject's raw identifiers also live in
            # import rows (normalized_payload.user_id), so a "COMPLETED" deletion
            # must remove those too. Notification events and the count-only audit
            # action logs are intentionally retained as process-audit evidence
            # that the workflow happened; those are governed by retention cleanup.
            import_rows = self._delete_subject_import_rows(session, subject_id, tenant_id=tenant_id)
            session.delete(user)
            session.commit()
            return {
                "users": 1,
                "learning_records": learning_records,
                "enrollments": enrollments,
                "import_rows": import_rows,
            }

    @staticmethod
    def _delete_subject_import_rows(session: Session, subject_id: str, *, tenant_id: str) -> int:
        """Delete import rows whose normalized payload carries the subject id.

        Import rows link to a batch (tenant-scoped) and hold the subject id inside
        a JSON payload, so we resolve the tenant's batches and filter in Python to
        stay portable across SQLite and PostgreSQL JSON dialects.
        """
        batch_ids = [
            row[0]
            for row in session.query(DBImportBatch.id)
            .where(DBImportBatch.tenant_id == tenant_id)
            .all()
        ]
        if not batch_ids:
            return 0
        deleted = 0
        rows = session.query(DBImportRow).where(DBImportRow.batch_id.in_(batch_ids)).all()
        for row in rows:
            payload = row.normalized_payload or {}
            if payload.get("user_id") == subject_id:
                session.delete(row)
                deleted += 1
        return deleted

    def save_legal_hold(self, hold: dict[str, Any]) -> None:
        with self._session() as session:
            session.add(
                DBLegalHold(
                    id=hold["id"],
                    tenant_id=hold["tenant_id"],
                    subject_id=hold.get("subject_id"),
                    scope=hold["scope"],
                    reason=hold["reason"],
                    status=hold.get("status", "ACTIVE"),
                    created_by=hold["created_by"],
                    created_at=hold.get("created_at") or utc_now(),
                    hold_metadata=hold.get("metadata") or {},
                )
            )
            session.commit()

    def get_legal_hold(self, hold_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            hold = session.get(DBLegalHold, hold_id)
            return self._to_legal_hold_dict(hold) if hold else None

    def list_active_legal_holds(
        self,
        *,
        tenant_id: str,
        subject_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBLegalHold).where(
                DBLegalHold.tenant_id == tenant_id,
                DBLegalHold.status == "ACTIVE",
            )
            if subject_id is not None:
                # A subject's deletion is blocked by a hold naming that subject OR
                # by any tenant-wide/system-wide hold. Omitting "system" here was a
                # spoliation gap: a system hold silently failed to block deletion.
                query = query.where(
                    (DBLegalHold.subject_id == subject_id)
                    | (DBLegalHold.scope.in_(_TENANT_WIDE_HOLD_SCOPES))
                )
            return [self._to_legal_hold_dict(row) for row in query.all()]

    def resolve_active_holds(self, *, tenant_id: str) -> HoldDecision:
        """Evaluate all active holds for a tenant once, for uniform enforcement.

        Returns whether a tenant-wide/system hold blocks everything, plus the set
        of subject ids under a subject-scoped hold. Every retention-eligibility
        query routes through this so the scope vocabulary cannot drift again.
        """
        with self._session() as session:
            active = (
                session.query(DBLegalHold)
                .where(DBLegalHold.tenant_id == tenant_id, DBLegalHold.status == "ACTIVE")
                .all()
            )
        tenant_blocked = any(hold.scope in _TENANT_WIDE_HOLD_SCOPES for hold in active)
        held_subject_ids = frozenset(
            hold.subject_id
            for hold in active
            if hold.subject_id and hold.scope == "subject"
        )
        return HoldDecision(tenant_blocked=tenant_blocked, held_subject_ids=held_subject_ids)

    def release_legal_hold(
        self,
        hold_id: str,
        *,
        released_by: str,
        released_at: datetime,
    ) -> None:
        with self._session() as session:
            hold = session.get(DBLegalHold, hold_id)
            if hold is None:
                return
            hold.status = "RELEASED"
            hold.released_by = released_by
            hold.released_at = released_at
            session.commit()

    def save_retention_policy(
        self,
        *,
        tenant_id: str,
        policy: dict[str, Any],
        updated_by: str,
        updated_at: datetime,
    ) -> None:
        with self._session() as session:
            row = session.get(DBRetentionPolicy, tenant_id)
            if row is None:
                row = DBRetentionPolicy(tenant_id=tenant_id, updated_by=updated_by)
                session.add(row)
            row.policy = policy
            row.updated_by = updated_by
            row.updated_at = updated_at
            session.commit()

    def get_retention_policy(self, tenant_id: str) -> dict[str, Any]:
        with self._session() as session:
            row = session.get(DBRetentionPolicy, tenant_id)
            return dict(row.policy or {}) if row else {}

    def list_retention_eligible_privacy_request_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        closed_statuses = {"COMPLETED", "REJECTED", "CANCELLED"}
        holds = self.resolve_active_holds(tenant_id=tenant_id)
        if holds.tenant_blocked:
            return []
        with self._session() as session:
            candidates = (
                session.query(DBPrivacyRequest.id, DBPrivacyRequest.subject_id)
                .where(
                    DBPrivacyRequest.tenant_id == tenant_id,
                    DBPrivacyRequest.created_at < cutoff,
                    DBPrivacyRequest.status.in_(closed_statuses),
                )
                .all()
            )
        # Privacy requests carry subject_id, so we can exclude held subjects
        # precisely rather than blocking the whole dataset.
        return [row.id for row in candidates if row.subject_id not in holds.held_subject_ids]

    def list_retention_eligible_import_batch_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        terminal_statuses = {"PROMOTED", "REJECTED", "EXPIRED", "PROMOTION_FAILED"}
        # Import batches have no indexed subject linkage, so any active hold of any
        # scope fails closed: never purge while a hold exists rather than risk
        # deleting a held subject's raw source payloads.
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBImportBatch.id)
                .where(
                    DBImportBatch.tenant_id == tenant_id,
                    DBImportBatch.created_at < cutoff,
                    DBImportBatch.status.in_(terminal_statuses),
                )
                .all()
            )
            return [row[0] for row in rows]

    def count_import_rows_for_batches(self, batch_ids: list[str]) -> int:
        if not batch_ids:
            return 0
        with self._session() as session:
            return session.query(DBImportRow).where(DBImportRow.batch_id.in_(batch_ids)).count()

    def count_import_decisions_for_batches(self, batch_ids: list[str]) -> int:
        if not batch_ids:
            return 0
        with self._session() as session:
            return (
                session.query(DBImportDecision)
                .where(DBImportDecision.batch_id.in_(batch_ids))
                .count()
            )

    def list_retention_eligible_ai_proposal_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        disposable_statuses = {"REJECTED", "EXPIRED", "CANCELLED"}
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBAIProposal.id)
                .where(
                    DBAIProposal.tenant_id == tenant_id,
                    DBAIProposal.created_at < cutoff,
                    DBAIProposal.status.in_(disposable_statuses),
                )
                .all()
            )
            return [row[0] for row in rows]

    def list_retention_eligible_evidence_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBEvidenceLedger.id)
                .where(
                    DBEvidenceLedger.tenant_id == tenant_id,
                    DBEvidenceLedger.timestamp < cutoff,
                )
                .all()
            )
            return [row[0] for row in rows]

    def list_retention_eligible_action_log_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBAuditActionLog.id)
                .where(
                    DBAuditActionLog.tenant_id == tenant_id,
                    DBAuditActionLog.created_at < cutoff,
                )
                .all()
            )
            return [row[0] for row in rows]

    def purge_retention_eligible(
        self,
        *,
        tenant_id: str,
        privacy_request_ids: list[str],
        import_batch_ids: list[str],
        ai_proposal_ids: list[str],
        evidence_ids: list[str],
        action_log_ids: list[str],
        actor_id: str,
        surface: str,
        request_id: str | None,
        log_metadata: dict[str, Any],
    ) -> dict[str, int]:
        """Delete all retention-eligible records AND write the audit record atomically.

        Every destructive delete plus the ``privacy.retention.run`` audit-log entry
        commit (or roll back) together in one transaction. This closes the
        chain-of-custody gap where a mid-sequence failure could leave PII/evidence
        irreversibly destroyed with no audit trail of what was removed. Each DELETE
        is tenant-scoped (defense in depth) so a wrong id list cannot reach across
        tenants. Returns the per-dataset deleted counts.
        """

        def _delete(session: Session, model: Any, ids: list[str], *, tenant_scoped: bool) -> int:
            if not ids:
                return 0
            clause = model.id.in_(ids)
            if tenant_scoped:
                clause = clause & (model.tenant_id == tenant_id)
            return (
                session.query(model)
                .where(clause)
                .delete(synchronize_session=False)
            )

        with self._session() as session:
            try:
                deleted_import_decisions = 0
                deleted_import_rows = 0
                if import_batch_ids:
                    deleted_import_decisions = (
                        session.query(DBImportDecision)
                        .where(DBImportDecision.batch_id.in_(import_batch_ids))
                        .delete(synchronize_session=False)
                    )
                    deleted_import_rows = (
                        session.query(DBImportRow)
                        .where(DBImportRow.batch_id.in_(import_batch_ids))
                        .delete(synchronize_session=False)
                    )
                if ai_proposal_ids:
                    session.query(DBAIProvenance).where(
                        DBAIProvenance.proposal_id.in_(ai_proposal_ids)
                    ).delete(synchronize_session=False)
                deleted_counts = {
                    "privacy_requests": _delete(
                        session, DBPrivacyRequest, privacy_request_ids, tenant_scoped=True
                    ),
                    "raw_import_rows": deleted_import_rows,
                    "import_decisions": deleted_import_decisions,
                    "ai_proposals": _delete(
                        session, DBAIProposal, ai_proposal_ids, tenant_scoped=True
                    ),
                    "evidence_ledger": _delete(
                        session, DBEvidenceLedger, evidence_ids, tenant_scoped=True
                    ),
                    "action_logs": _delete(
                        session, DBAuditActionLog, action_log_ids, tenant_scoped=True
                    ),
                }
                session.add(
                    DBAuditActionLog(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        actor_id=actor_id,
                        surface=surface,
                        action="privacy.retention.run",
                        object_type="retention_policy",
                        object_id=tenant_id,
                        result="success",
                        request_id=request_id,
                        redacted_metadata={**log_metadata, "deleted_counts": deleted_counts},
                        created_at=utc_now(),
                    )
                )
                session.commit()
                return deleted_counts
            except Exception:
                session.rollback()
                raise

    def clear_all(self) -> None:
        with self._session() as session:
            session.query(DBEnrollment).delete()
            session.query(DBLearningRecord).delete()
            session.query(DBCourse).delete()
            session.query(DBUser).delete()
            session.query(DBEvidenceLedger).delete()
            session.query(DBImportDecision).delete()
            session.query(DBImportRow).delete()
            session.query(DBImportBatch).delete()
            session.query(DBAIProvenance).delete()
            session.query(DBAIProposal).delete()
            session.query(DBApproval).delete()
            session.query(DBPrivacyRequest).delete()
            session.query(DBLegalHold).delete()
            session.query(DBRetentionPolicy).delete()
            session.commit()

