"""Tests for SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import date, datetime

from complyos.models.database import (
    DBCourse,
    DBEnrollment,
    DBEvidenceLedger,
    DBLearningRecord,
    DBUser,
    init_db,
)


class TestDatabaseInit:
    def test_init_db_creates_tables(self, tmp_path):
        db_path = tmp_path / "test.db"
        sessionmaker = init_db(str(db_path))
        assert db_path.exists()

        # Verify we can create a session
        session = sessionmaker()
        assert session is not None
        session.close()


class TestDBUser:
    def test_create_and_retrieve_user(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        user = DBUser(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 15),
            employment_status="active",
        )
        session.add(user)
        session.commit()

        retrieved = session.query(DBUser).filter_by(id="u1").first()
        assert retrieved is not None
        assert retrieved.first_name == "Alice"
        assert retrieved.department == "Engineering"
        assert retrieved.enrollments == []

        session.close()

    def test_user_with_manager(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        user = DBUser(
            id="u2",
            employee_id="E002",
            email="bob@example.com",
            first_name="Bob",
            last_name="Jones",
            department="HR",
            region="EU",
            hire_date=date(2022, 6, 1),
            manager_id="u1",
            job_title="HR Specialist",
        )
        session.add(user)
        session.commit()

        retrieved = session.query(DBUser).filter_by(id="u2").first()
        assert retrieved.manager_id == "u1"
        assert retrieved.job_title == "HR Specialist"
        session.close()


class TestDBCourse:
    def test_create_course(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        course = DBCourse(
            id="c1",
            code="SEC-101",
            title="Information Security Basics",
            description="Learn the basics of InfoSec",
            duration_minutes=60,
            mandatory=True,
            category="Compliance",
        )
        session.add(course)
        session.commit()

        retrieved = session.query(DBCourse).filter_by(id="c1").first()
        assert retrieved is not None
        assert retrieved.mandatory is True
        assert retrieved.duration_minutes == 60
        session.close()


class TestDBEnrollment:
    def test_enrollment_relationships(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        user = DBUser(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 15),
        )
        course = DBCourse(
            id="c1",
            code="SEC-101",
            title="Information Security Basics",
            mandatory=True,
        )
        session.add_all([user, course])
        session.commit()

        enrollment = DBEnrollment(
            id="e1",
            user_id="u1",
            course_id="c1",
            status="in_progress",
            assigned_date=datetime(2024, 1, 1),
            due_date=date(2024, 2, 1),
            completion_percentage=50.0,
            score=85.5,
        )
        session.add(enrollment)
        session.commit()

        retrieved = session.query(DBEnrollment).filter_by(id="e1").first()
        assert retrieved.user.first_name == "Alice"
        assert retrieved.course.title == "Information Security Basics"
        assert retrieved.completion_percentage == 50.0
        assert retrieved.score == 85.5
        session.close()

    def test_cascade_delete(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        user = DBUser(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 15),
        )
        course = DBCourse(
            id="c1",
            code="SEC-101",
            title="Security",
            mandatory=True,
        )
        session.add_all([user, course])
        session.commit()

        enrollment = DBEnrollment(
            id="e1",
            user_id="u1",
            course_id="c1",
            status="completed",
        )
        session.add(enrollment)
        session.commit()

        # Deleting user should cascade to enrollments
        session.delete(user)
        session.commit()

        assert session.query(DBEnrollment).filter_by(id="e1").first() is None
        session.close()


class TestDBLearningRecord:
    def test_create_and_retrieve_learning_record(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        user = DBUser(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 15),
        )
        course = DBCourse(
            id="c1",
            code="SEC-101",
            title="Information Security Basics",
            mandatory=True,
        )
        session.add_all([user, course])
        session.commit()

        record = DBLearningRecord(
            id="lr1",
            user_id="u1",
            course_id="c1",
            source_system="workday",
            source_record_id="wd-123",
            status="completed",
            assigned_date=datetime(2024, 1, 1, 9, 0, 0),
            due_date=date(2024, 2, 1),
            completed_date=datetime(2024, 1, 15, 16, 30, 0),
            completion_percentage=100.0,
            score=92.5,
            exempt=False,
            expires_at=date(2025, 1, 15),
            raw_source_hash="sha256:abc123",
            source_payload={"provider": "workday", "version": 3},
        )
        session.add(record)
        session.commit()

        retrieved = session.query(DBLearningRecord).filter_by(id="lr1").first()
        assert retrieved is not None
        assert retrieved.source_system == "workday"
        assert retrieved.source_record_id == "wd-123"
        assert retrieved.expires_at == date(2025, 1, 15)
        assert retrieved.source_payload == {"provider": "workday", "version": 3}
        session.close()


class TestDBEvidenceLedger:
    def test_create_ledger_entry(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        entry = DBEvidenceLedger(
            id="el1",
            timestamp=datetime(2024, 6, 1, 12, 0, 0),
            query_type="audit_gaps",
            query_params='{"department": "Engineering"}',
            raw_data_hash="abc123",
            transformation_steps="filter->aggregate->hash",
            output_hash="def456",
            output_summary="5 gaps found in Engineering",
        )
        session.add(entry)
        session.commit()

        retrieved = session.query(DBEvidenceLedger).filter_by(id="el1").first()
        assert retrieved is not None
        assert retrieved.query_type == "audit_gaps"
        assert retrieved.output_hash == "def456"
        session.close()
