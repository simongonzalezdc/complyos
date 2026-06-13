"""Repository layer for persisting domain models to SQLite."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from complyos.core.privacy_repo import PrivacyRepositoryMixin
from complyos.core.repository_base import RepositoryBase
from complyos.core.repository_mappers import RepositoryMappers
from complyos.core.time import utc_now
from complyos.models.database import (
    DBAIProposal,
    DBAIProvenance,
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
    DBNotificationDelivery,
    DBNotificationEvent,
    DBNotificationPreference,
    DBSourceIntelJobExecution,
    DBSourceIntelProposal,
    DBSourceIntelRun,
    DBSourceIntelSchedule,
    DBUser,
)
from complyos.models.domain import Course, Enrollment, LearningRecord, LearningRecordStatus, User
from complyos.source_intel.monitor import SourceMonitorRun


class LocalRepository(PrivacyRepositoryMixin, RepositoryBase, RepositoryMappers):
    """CRUD operations backed by local SQLite via SQLAlchemy.

    Composed from per-aggregate mixins (privacy, ...) plus RepositoryBase
    (session factory + shared helpers) and RepositoryMappers (ORM-row
    serialization). This class holds the audit/import/source-intel/notification
    aggregates; privacy/retention/legal-hold lives in PrivacyRepositoryMixin.
    """

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

