"""Tests for the LocalRepository layer."""

from __future__ import annotations

from datetime import date, datetime

from complyos.core.repository import LocalRepository
from complyos.models.domain import Course, Enrollment, EnrollmentStatus, User


class TestUserRepository:
    def test_save_and_get_user(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        user = User(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 15),
            employment_status="active",
            manager_id="m1",
        )
        repo.save_user(user)

        retrieved = repo.get_user("u1")
        assert retrieved is not None
        assert retrieved.first_name == "Alice"
        assert retrieved.department == "Engineering"
        assert retrieved.manager_id == "m1"

    def test_get_missing_user_returns_none(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        assert repo.get_user("nonexistent") is None

    def test_update_existing_user(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        user = User(
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
        repo.save_user(user)

        user.department = "HR"
        repo.save_user(user)

        retrieved = repo.get_user("u1")
        assert retrieved.department == "HR"

    def test_list_users_filtered(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Engineering",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_user(
            User(
                id="u2",
                employee_id="E002",
                email="b@example.com",
                first_name="B",
                last_name="B",
                department="HR",
                region="EU",
                hire_date=date(2023, 1, 1),
                employment_status="terminated",
            )
        )

        eng = repo.list_users(department="Engineering")
        assert len(eng) == 1
        assert eng[0].id == "u1"

        us = repo.list_users(region="US")
        assert len(us) == 1

        active = repo.list_users(employment_status="active")
        assert len(active) == 1


class TestCourseRepository:
    def test_save_and_get_course(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        course = Course(
            id="c1",
            code="SEC-101",
            title="Security",
            description="InfoSec basics",
            duration_minutes=60,
            mandatory=True,
            category="Compliance",
        )
        repo.save_course(course)

        retrieved = repo.get_course("c1")
        assert retrieved is not None
        assert retrieved.mandatory is True
        assert retrieved.duration_minutes == 60

    def test_list_courses_mandatory_filter(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        repo.save_course(
            Course(
                id="c1",
                code="SEC-101",
                title="Security",
                mandatory=True,
            )
        )
        repo.save_course(
            Course(
                id="c2",
                code="LEAD-101",
                title="Leadership",
                mandatory=False,
            )
        )

        mandatory = repo.list_courses(mandatory=True)
        assert len(mandatory) == 1
        assert mandatory[0].id == "c1"

        all_courses = repo.list_courses()
        assert len(all_courses) == 2


class TestEnrollmentRepository:
    def test_save_and_list_enrollments(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        # Seed user and course first (FK integrity)
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Engineering",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_course(Course(id="c1", code="SEC-101", title="Security"))

        enrollment = Enrollment(
            id="e1",
            user_id="u1",
            course_id="c1",
            status=EnrollmentStatus.IN_PROGRESS,
            assigned_date=datetime(2024, 1, 1),
            due_date=date(2024, 2, 1),
            completion_percentage=50.0,
            score=85.0,
        )
        repo.save_enrollment(enrollment)

        enrollments = repo.list_enrollments(user_id="u1")
        assert len(enrollments) == 1
        assert enrollments[0].status == EnrollmentStatus.IN_PROGRESS
        assert enrollments[0].score == 85.0

    def test_list_enrollments_by_status(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Engineering",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_course(Course(id="c1", code="SEC-101", title="Security"))

        repo.save_enrollment(
            Enrollment(
                id="e1",
                user_id="u1",
                course_id="c1",
                status=EnrollmentStatus.COMPLETED,
            )
        )
        repo.save_enrollment(
            Enrollment(
                id="e2",
                user_id="u1",
                course_id="c1",
                status=EnrollmentStatus.IN_PROGRESS,
            )
        )

        completed = repo.list_enrollments(status="completed")
        assert len(completed) == 1


class TestSyncHelpers:
    def test_sync_users(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        users = [
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
            User(
                id="u2",
                employee_id="E002",
                email="b@example.com",
                first_name="B",
                last_name="B",
                department="HR",
                region="EU",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
        ]
        assert repo.sync_users(users) == 2
        assert len(repo.list_users()) == 2

    def test_clear_all(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "test.db"))
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_course(Course(id="c1", code="SEC-101", title="Security"))
        repo.clear_all()

        assert repo.get_user("u1") is None
        assert repo.get_course("c1") is None
