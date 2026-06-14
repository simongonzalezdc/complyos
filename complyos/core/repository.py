"""Repository layer for persisting domain models to SQLite."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from complyos.core.import_repo import ImportRepositoryMixin
from complyos.core.notification_repo import NotificationRepositoryMixin
from complyos.core.privacy_repo import PrivacyRepositoryMixin
from complyos.core.repository_base import RepositoryBase
from complyos.core.repository_mappers import RepositoryMappers
from complyos.core.role_binding_repo import RoleBindingRepositoryMixin
from complyos.core.source_intel_repo import SourceIntelRepositoryMixin
from complyos.core.time import utc_now
from complyos.models.database import (
    DBAuditActionLog,
    DBAuditSnapshot,
    DBCourse,
    DBEnrollment,
    DBEvidenceLedger,
    DBImportBatch,
    DBImportRow,
    DBLearningRecord,
    DBTenant,
    DBUser,
)
from complyos.models.domain import Course, Enrollment, LearningRecord, LearningRecordStatus, User


class LocalRepository(
    PrivacyRepositoryMixin,
    ImportRepositoryMixin,
    SourceIntelRepositoryMixin,
    NotificationRepositoryMixin,
    RoleBindingRepositoryMixin,
    RepositoryBase,
    RepositoryMappers,
):
    """CRUD operations backed by local SQLite via SQLAlchemy.

    This class holds the core audit aggregate (users, courses, enrollments,
    learning records, sync, audit snapshots, evidence ledger + action log) and
    composes the other aggregates as mixins: privacy/retention/legal-hold,
    imports + AI proposals, source-intelligence, and the notification outbox.
    RepositoryBase provides the session factory + shared helpers; mappers come
    from RepositoryMappers. Callers still use ``repository.<method>`` unchanged.
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
    # Tenant governance metadata
    # ------------------------------------------------------------------
    def get_tenant_metadata(self, tenant_id: str) -> dict[str, Any]:
        """Return a tenant's data-governance metadata, tenant-scoped by id.

        Surfaces the GDPR-shaped fields a buyer/auditor asks for (data region,
        processing purpose, data categories, retention, subprocessors). A missing
        tenant row yields sensible empties so callers never have to special-case
        an unseeded tenant.
        """
        with self._session() as session:
            row = session.get(DBTenant, tenant_id)
            if row is None:
                return {
                    "data_region": None,
                    "processing_purpose": None,
                    "data_categories": [],
                    "retention_policy": {},
                    "subprocessor_profile": {},
                }
            return {
                "data_region": row.data_region,
                "processing_purpose": row.processing_purpose,
                "data_categories": list(row.data_categories or []),
                "retention_policy": dict(row.retention_policy or {}),
                "subprocessor_profile": dict(row.subprocessor_profile or {}),
            }

