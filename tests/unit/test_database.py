"""Tests for SQLAlchemy ORM models."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import inspect, text

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

    def test_init_db_records_schema_migrations_and_source_intel_job_tables(self, tmp_path):
        sessionmaker = init_db(str(tmp_path / "migrated.db"))
        session = sessionmaker()
        assert session.bind is not None
        table_names = set(inspect(session.bind).get_table_names())

        assert "schema_migrations" in table_names
        assert "source_intel_schedules" in table_names
        assert "source_intel_job_executions" in table_names
        assert "notification_events" in table_names
        assert "notification_deliveries" in table_names
        assert "notification_preferences" in table_names
        assert "inbound_webhook_events" in table_names

        rows = session.execute(text("SELECT migration_id FROM schema_migrations")).scalars().all()
        assert "20260612_source_intel_hardening" in rows
        assert "20260613_notification_outbox_hooks" in rows
        assert "20260613_notification_preferences" in rows
        assert "20260613_inbound_webhook_events" in rows
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
    def test_enrollment_persists_and_resolves_parents_by_query(self, tmp_path):
        """Parents are resolved by explicit query, not ORM relationship navigation.

        ``user_id``/``course_id`` are source-system identifiers rather than
        enforced foreign keys, so the application looks up the learner/item by
        id when it needs them instead of traversing a relationship attribute.
        """
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
        assert retrieved is not None
        assert retrieved.user_id == "u1"
        assert retrieved.course_id == "c1"
        assert retrieved.completion_percentage == 50.0
        assert retrieved.score == 85.5

        parent_user = session.query(DBUser).filter_by(id=retrieved.user_id).first()
        parent_course = session.query(DBCourse).filter_by(id=retrieved.course_id).first()
        assert parent_user is not None and parent_user.first_name == "Alice"
        assert parent_course is not None and parent_course.title == "Information Security Basics"
        session.close()

    def test_records_can_be_stored_without_parent_rows(self, tmp_path):
        """Learning records/enrollments may reference subjects/items not synced locally.

        ``LearningRecord`` is a normalized cross-LMS *source* record: CSV imports
        promote them standalone, before (or without) the corresponding learner/
        item ever being synced into ``users``/``courses``. This test locks in
        that intentional model so a future re-introduction of a hard foreign key
        (which would break standalone import) fails loudly here.
        """
        sessionmaker = init_db(str(tmp_path / "test.db"))
        session = sessionmaker()

        # No DBUser / DBCourse rows are created.
        enrollment = DBEnrollment(
            id="e-orphan",
            user_id="u-unsynced",
            course_id="c-unsynced",
            status="completed",
        )
        record = DBLearningRecord(
            id="lr-orphan",
            user_id="u-unsynced",
            course_id="c-unsynced",
            source_system="csv",
            status="completed",
        )
        session.add_all([enrollment, record])
        session.commit()

        assert session.query(DBEnrollment).filter_by(id="e-orphan").first() is not None
        assert session.query(DBLearningRecord).filter_by(id="lr-orphan").first() is not None
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
