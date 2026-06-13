"""Repository layer for persisting domain models to SQLite."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

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
    DBLearningRecord,
    DBLegalHold,
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


class LocalRepository:
    """CRUD operations backed by local SQLite via SQLAlchemy."""

    def __init__(self, db_path: str = "complyos.db", database_url: str | None = None) -> None:
        self._sessionmaker = init_db(database_url or db_path)

    def _session(self) -> Session:
        return self._sessionmaker()

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
                for row_id, record in row_record_pairs:
                    db_record = session.get(DBLearningRecord, record.id)
                    if db_record is None:
                        db_record = DBLearningRecord(id=record.id)
                        session.add(db_record)

                    db_record.user_id = record.user_id
                    db_record.course_id = record.course_id
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

                batch = session.get(DBImportBatch, batch_id)
                if batch is None:
                    raise ValueError(f"unknown import batch during promotion: {batch_id}")
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
                        transformation_steps=json.dumps(
                            evidence_entry["transformation_steps"]
                        ),
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
                    timestamp=timestamp or datetime.utcnow(),
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
                    created_at=created_at or datetime.utcnow(),
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
        timestamp = created_at or datetime.utcnow()
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
            rows = (
                query.order_by(DBSourceIntelProposal.created_at.desc())
                .limit(limit)
                .all()
            )
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
            proposal.decided_at = decided_at or datetime.utcnow()
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
        timestamp = created_at or datetime.utcnow()
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
            rows = (
                query.order_by(DBSourceIntelJobExecution.started_at.desc())
                .limit(limit)
                .all()
            )
            return [self._to_source_intel_job_execution_dict(row) for row in rows]

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
                created_at=batch.get("created_at") or datetime.utcnow(),
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
                    decided_at=decision.get("decided_at") or datetime.utcnow(),
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
                    created_at=proposal.get("created_at") or datetime.utcnow(),
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
                    created_at=request.get("created_at") or datetime.utcnow(),
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
                    created_at=approval.get("created_at") or datetime.utcnow(),
                )
            )
            session.commit()
        return approval_id

    def get_subject_export(self, subject_id: str, *, tenant_id: str) -> dict[str, Any]:
        with self._session() as session:
            user = session.get(DBUser, subject_id)
            if user is not None:
                user_tenant = (user.custom_attributes or {}).get("tenant_id", "local-default")
                if user_tenant != tenant_id:
                    user = None
            learning_records = (
                session.query(DBLearningRecord)
                .where(DBLearningRecord.user_id == subject_id)
                .all()
                if user is not None
                else []
            )
            enrollments = (
                session.query(DBEnrollment).where(DBEnrollment.user_id == subject_id).all()
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
            user = session.get(DBUser, subject_id)
            if user is None:
                return {"users": 0, "learning_records": 0, "enrollments": 0}
            user_tenant = (user.custom_attributes or {}).get("tenant_id", "local-default")
            if user_tenant != tenant_id:
                return {"users": 0, "learning_records": 0, "enrollments": 0}

            learning_records = (
                session.query(DBLearningRecord)
                .where(DBLearningRecord.user_id == subject_id)
                .delete(synchronize_session=False)
            )
            enrollments = (
                session.query(DBEnrollment)
                .where(DBEnrollment.user_id == subject_id)
                .delete(synchronize_session=False)
            )
            session.delete(user)
            session.commit()
            return {
                "users": 1,
                "learning_records": learning_records,
                "enrollments": enrollments,
            }

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
                    created_at=hold.get("created_at") or datetime.utcnow(),
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
                query = query.where(
                    (DBLegalHold.subject_id == subject_id) | (DBLegalHold.scope == "tenant")
                )
            return [self._to_legal_hold_dict(row) for row in query.all()]

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
        with self._session() as session:
            candidates = (
                session.query(DBPrivacyRequest)
                .where(
                    DBPrivacyRequest.tenant_id == tenant_id,
                    DBPrivacyRequest.created_at < cutoff,
                    DBPrivacyRequest.status.in_(closed_statuses),
                )
                .all()
            )
            active_holds = (
                session.query(DBLegalHold)
                .where(DBLegalHold.tenant_id == tenant_id, DBLegalHold.status == "ACTIVE")
                .all()
            )
            tenant_hold_active = any(hold.scope == "tenant" for hold in active_holds)
            held_subjects = {hold.subject_id for hold in active_holds if hold.subject_id}
            if tenant_hold_active:
                return []
            return [
                request.id
                for request in candidates
                if request.subject_id not in held_subjects
            ]

    def list_retention_eligible_import_batch_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        terminal_statuses = {"PROMOTED", "REJECTED", "EXPIRED", "PROMOTION_FAILED"}
        with self._session() as session:
            tenant_hold_active = (
                session.query(DBLegalHold)
                .where(
                    DBLegalHold.tenant_id == tenant_id,
                    DBLegalHold.status == "ACTIVE",
                    DBLegalHold.scope == "tenant",
                )
                .first()
                is not None
            )
            if tenant_hold_active:
                return []
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
            return (
                session.query(DBImportRow)
                .where(DBImportRow.batch_id.in_(batch_ids))
                .count()
            )

    def count_import_decisions_for_batches(self, batch_ids: list[str]) -> int:
        if not batch_ids:
            return 0
        with self._session() as session:
            return (
                session.query(DBImportDecision)
                .where(DBImportDecision.batch_id.in_(batch_ids))
                .count()
            )

    def delete_import_payloads_for_batches(self, batch_ids: list[str]) -> dict[str, int]:
        if not batch_ids:
            return {"raw_import_rows": 0, "import_decisions": 0}
        with self._session() as session:
            import_decisions = (
                session.query(DBImportDecision)
                .where(DBImportDecision.batch_id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            raw_import_rows = (
                session.query(DBImportRow)
                .where(DBImportRow.batch_id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            session.commit()
            return {
                "raw_import_rows": raw_import_rows,
                "import_decisions": import_decisions,
            }

    def list_retention_eligible_ai_proposal_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        disposable_statuses = {"REJECTED", "EXPIRED", "CANCELLED"}
        with self._session() as session:
            tenant_hold_active = (
                session.query(DBLegalHold)
                .where(
                    DBLegalHold.tenant_id == tenant_id,
                    DBLegalHold.status == "ACTIVE",
                    DBLegalHold.scope == "tenant",
                )
                .first()
                is not None
            )
            if tenant_hold_active:
                return []
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

    def delete_ai_proposals_by_ids(self, proposal_ids: list[str]) -> int:
        if not proposal_ids:
            return 0
        with self._session() as session:
            session.query(DBAIProvenance).where(
                DBAIProvenance.proposal_id.in_(proposal_ids)
            ).delete(synchronize_session=False)
            deleted = (
                session.query(DBAIProposal)
                .where(DBAIProposal.id.in_(proposal_ids))
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted

    def list_retention_eligible_evidence_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        with self._session() as session:
            tenant_hold_active = (
                session.query(DBLegalHold)
                .where(
                    DBLegalHold.tenant_id == tenant_id,
                    DBLegalHold.status == "ACTIVE",
                    DBLegalHold.scope == "tenant",
                )
                .first()
                is not None
            )
            if tenant_hold_active:
                return []
            rows = (
                session.query(DBEvidenceLedger.id)
                .where(
                    DBEvidenceLedger.tenant_id == tenant_id,
                    DBEvidenceLedger.timestamp < cutoff,
                )
                .all()
            )
            return [row[0] for row in rows]

    def delete_evidence_entries_by_ids(self, evidence_ids: list[str]) -> int:
        if not evidence_ids:
            return 0
        with self._session() as session:
            deleted = (
                session.query(DBEvidenceLedger)
                .where(DBEvidenceLedger.id.in_(evidence_ids))
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted

    def list_retention_eligible_action_log_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        with self._session() as session:
            tenant_hold_active = (
                session.query(DBLegalHold)
                .where(
                    DBLegalHold.tenant_id == tenant_id,
                    DBLegalHold.status == "ACTIVE",
                    DBLegalHold.scope == "tenant",
                )
                .first()
                is not None
            )
            if tenant_hold_active:
                return []
            rows = (
                session.query(DBAuditActionLog.id)
                .where(
                    DBAuditActionLog.tenant_id == tenant_id,
                    DBAuditActionLog.created_at < cutoff,
                )
                .all()
            )
            return [row[0] for row in rows]

    def delete_action_logs_by_ids(self, action_log_ids: list[str]) -> int:
        if not action_log_ids:
            return 0
        with self._session() as session:
            deleted = (
                session.query(DBAuditActionLog)
                .where(DBAuditActionLog.id.in_(action_log_ids))
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted

    def delete_privacy_requests_by_ids(self, request_ids: list[str]) -> int:
        if not request_ids:
            return 0
        with self._session() as session:
            deleted = (
                session.query(DBPrivacyRequest)
                .where(DBPrivacyRequest.id.in_(request_ids))
                .delete(synchronize_session=False)
            )
            session.commit()
            return deleted

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

    # ------------------------------------------------------------------
    # Domain mappers
    # ------------------------------------------------------------------
    @staticmethod
    def _to_user(db: DBUser) -> User:
        from complyos.models.domain import EmploymentStatus

        return User(
            id=db.id,
            employee_id=db.employee_id,
            email=db.email,
            first_name=db.first_name,
            last_name=db.last_name,
            department=db.department,
            region=db.region or "",
            hire_date=db.hire_date,
            employment_status=EmploymentStatus(db.employment_status),
            manager_id=db.manager_id,
            custom_attributes=db.custom_attributes or {},
        )

    @staticmethod
    def _to_course(db: DBCourse) -> Course:
        return Course(
            id=db.id,
            code=db.code,
            title=db.title,
            description=db.description,
            duration_minutes=db.duration_minutes,
            mandatory=db.mandatory,
            category=db.category,
        )

    @staticmethod
    def _to_enrollment(db: DBEnrollment) -> Enrollment:
        from complyos.models.domain import EnrollmentStatus

        return Enrollment(
            id=db.id,
            user_id=db.user_id,
            course_id=db.course_id,
            status=EnrollmentStatus(db.status),
            assigned_date=db.assigned_date,
            due_date=db.due_date,
            completed_date=db.completed_date,
            completion_percentage=db.completion_percentage,
            score=db.score,
        )

    @staticmethod
    def _to_learning_record(db: DBLearningRecord) -> LearningRecord:
        return LearningRecord(
            id=db.id,
            user_id=db.user_id,
            course_id=db.course_id,
            source_system=db.source_system,
            source_record_id=db.source_record_id,
            status=LearningRecordStatus(db.status),
            assigned_date=db.assigned_date,
            due_date=db.due_date,
            completed_date=db.completed_date,
            completion_percentage=db.completion_percentage,
            score=db.score,
            exempt=db.exempt,
            expires_at=db.expires_at,
            raw_source_hash=db.raw_source_hash,
            source_payload=db.source_payload or {},
        )

    @staticmethod
    def _to_evidence_dict(db: DBEvidenceLedger) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "timestamp": db.timestamp,
            "query_type": db.query_type,
            "query_params": json.loads(db.query_params or "{}"),
            "raw_data_hash": db.raw_data_hash,
            "transformation_steps": json.loads(db.transformation_steps or "[]"),
            "output_hash": db.output_hash,
            "output_summary": db.output_summary,
        }

    @staticmethod
    def _to_action_log_dict(db: DBAuditActionLog) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "actor_id": db.actor_id,
            "surface": db.surface,
            "action": db.action,
            "object_type": db.object_type,
            "object_id": db.object_id,
            "result": db.result,
            "request_id": db.request_id,
            "redacted_metadata": db.redacted_metadata or {},
            "created_at": db.created_at,
        }

    @staticmethod
    def _to_import_batch_dict(db: DBImportBatch) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "source_system": db.source_system,
            "profile": db.profile,
            "raw_file_hash": db.raw_file_hash,
            "status": db.status,
            "idempotency_key": db.idempotency_key,
            "created_by": db.created_by,
            "promoted_by": db.promoted_by,
            "created_at": db.created_at,
            "promoted_at": db.promoted_at,
            "metadata": db.batch_metadata or {},
        }

    @staticmethod
    def _to_import_row_dict(db: DBImportRow) -> dict[str, Any]:
        return {
            "id": db.id,
            "batch_id": db.batch_id,
            "row_number": db.row_number,
            "normalized_payload": db.normalized_payload or {},
            "raw_payload_hash": db.raw_payload_hash,
            "validation_status": db.validation_status,
            "rejection_codes": db.rejection_codes or [],
            "source_record_id": db.source_record_id,
            "issues": db.issues or [],
        }

    @staticmethod
    def _to_import_decision_dict(db: DBImportDecision) -> dict[str, Any]:
        return {
            "id": db.id,
            "batch_id": db.batch_id,
            "row_id": db.row_id,
            "decision_type": db.decision_type,
            "decision_payload": db.decision_payload or {},
            "decided_by": db.decided_by,
            "decided_at": db.decided_at,
            "reason": db.reason,
        }

    @staticmethod
    def _to_ai_proposal_dict(
        proposal: DBAIProposal,
        provenance: DBAIProvenance | None,
    ) -> dict[str, Any]:
        return {
            "id": proposal.id,
            "tenant_id": proposal.tenant_id,
            "proposal_type": proposal.proposal_type,
            "input_hash": proposal.input_hash,
            "output_hash": proposal.output_hash,
            "status": proposal.status,
            "created_by": proposal.created_by,
            "approved_by": proposal.approved_by,
            "created_at": proposal.created_at,
            "approved_at": proposal.approved_at,
            "output": proposal.output or {},
            "provenance": provenance.usage_metadata if provenance else {},
        }

    @staticmethod
    def _to_source_intel_proposal_dict(db: DBSourceIntelProposal) -> dict[str, Any]:
        payload = dict(db.payload or {})
        raw_signal = payload.get("signal")
        signal: dict[str, Any] = raw_signal if isinstance(raw_signal, dict) else {}
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "run_id": db.run_id,
            "adapter_name": db.adapter_name,
            "signal_type": db.signal_type,
            "source_id": db.source_id,
            "source_url": db.source_url,
            "source_hash": db.source_hash,
            "approval_state": db.approval_state,
            "decided_by": db.decided_by,
            "decided_at": db.decided_at,
            "created_at": db.created_at,
            "title": signal.get("title"),
            "summary": signal.get("summary"),
            "score": signal.get("score"),
            "payload": payload,
        }

    @staticmethod
    def _to_source_intel_schedule_dict(db: DBSourceIntelSchedule) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "name": db.name,
            "query": db.query,
            "source_ids": db.source_ids or [],
            "interval_hours": db.interval_hours,
            "mode": db.mode,
            "status": db.status,
            "created_by": db.created_by,
            "last_run_at": db.last_run_at,
            "created_at": db.created_at,
        }

    @staticmethod
    def _to_source_intel_job_execution_dict(db: DBSourceIntelJobExecution) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "schedule_id": db.schedule_id,
            "run_id": db.run_id,
            "status": db.status,
            "started_at": db.started_at,
            "finished_at": db.finished_at,
            "summary": db.summary or {},
            "error": db.error,
            "created_by": db.created_by,
        }

    @staticmethod
    def _to_privacy_request_dict(db: DBPrivacyRequest) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "subject_id": db.subject_id,
            "request_type": db.request_type,
            "status": db.status,
            "region": db.region,
            "opened_by": db.opened_by,
            "closed_by": db.closed_by,
            "created_at": db.created_at,
            "completed_at": db.completed_at,
            "metadata": db.request_metadata or {},
            "result_summary": db.result_summary or {},
        }

    @staticmethod
    def _to_legal_hold_dict(db: DBLegalHold) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "subject_id": db.subject_id,
            "scope": db.scope,
            "reason": db.reason,
            "status": db.status,
            "created_by": db.created_by,
            "released_by": db.released_by,
            "created_at": db.created_at,
            "released_at": db.released_at,
            "metadata": db.hold_metadata or {},
        }
