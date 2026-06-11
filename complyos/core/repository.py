"""Repository layer for persisting domain models to SQLite."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from complyos.models.database import (
    DBAuditSnapshot,
    DBCourse,
    DBEnrollment,
    DBEvidenceLedger,
    DBLearningRecord,
    DBUser,
    init_db,
)
from complyos.models.domain import Course, Enrollment, LearningRecord, LearningRecordStatus, User


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

    def clear_all(self) -> None:
        with self._session() as session:
            session.query(DBEnrollment).delete()
            session.query(DBLearningRecord).delete()
            session.query(DBCourse).delete()
            session.query(DBUser).delete()
            session.query(DBEvidenceLedger).delete()
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
