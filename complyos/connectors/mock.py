"""Mock connector for testing and demos."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.models.domain import Course, EmploymentStatus, Enrollment, EnrollmentStatus, User


class MockConnector(LMSConnector):
    """In-memory mock connector for testing without external dependencies."""

    name = "mock"

    def __init__(self, seed_data: bool = True):
        self.users: list[User] = []
        self.courses: list[Course] = []
        self.enrollments: list[Enrollment] = []
        if seed_data:
            self._seed()

    def _seed(self) -> None:
        today = date.today()
        self.users = [
            User(
                id="u1", employee_id="E001", email="alice@example.com",
                first_name="Alice", last_name="Smith", department="Engineering",
                region="US", hire_date=today - timedelta(days=100),
                employment_status=EmploymentStatus.ACTIVE,
            ),
            User(
                id="u2", employee_id="E002", email="bob@example.com",
                first_name="Bob", last_name="Jones", department="Engineering",
                region="US", hire_date=today - timedelta(days=200),
                employment_status=EmploymentStatus.ACTIVE,
            ),
            User(
                id="u3", employee_id="E003", email="carol@example.com",
                first_name="Carol", last_name="Davis", department="HR",
                region="US", hire_date=today - timedelta(days=50),
                employment_status=EmploymentStatus.ACTIVE,
            ),
            User(
                id="u4", employee_id="E004", email="david@example.com",
                first_name="David", last_name="Wilson", department="HR",
                region="MX", hire_date=today - timedelta(days=30),
                employment_status=EmploymentStatus.ACTIVE,
            ),
            User(
                id="u5", employee_id="E005", email="eve@example.com",
                first_name="Eve", last_name="Brown", department="Engineering",
                region="US", hire_date=today - timedelta(days=400),
                employment_status=EmploymentStatus.TERMINATED,
            ),
        ]
        self.courses = [
            Course(
                id="c1", code="RESPECT-101", title="Respectful Environment",
                mandatory=True, category="Compliance",
            ),
            Course(
                id="c2", code="SECURITY-101", title="Information Security Basics",
                mandatory=True, category="Compliance",
            ),
            Course(
                id="c3", code="LEAD-201", title="Leadership Fundamentals",
                mandatory=False, category="Development",
            ),
        ]
        self.enrollments = [
            # Alice: completed respect, missing security
            Enrollment(id="e1", user_id="u1", course_id="c1", status=EnrollmentStatus.COMPLETED,
                       assigned_date=datetime.now() - timedelta(days=90),
                       due_date=today - timedelta(days=60),
                       completed_date=datetime.now() - timedelta(days=70)),
            # Bob: in progress respect, missing security
            Enrollment(id="e2", user_id="u2", course_id="c1", status=EnrollmentStatus.IN_PROGRESS,
                       assigned_date=datetime.now() - timedelta(days=30),
                       due_date=today + timedelta(days=10),
                       completion_percentage=45.0),
            # Carol: missing both mandatory
            # David: enrolled in respect, not started, overdue
            Enrollment(id="e3", user_id="u4", course_id="c1", status=EnrollmentStatus.NOT_STARTED,
                       assigned_date=datetime.now() - timedelta(days=40),
                       due_date=today - timedelta(days=10)),
            # Eve (terminated): should not appear in audits
        ]

    async def authenticate(self) -> bool:
        return True

    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        result = self.users
        if filters:
            if "department" in filters:
                result = [u for u in result if u.department == filters["department"]]
            if "region" in filters:
                result = [u for u in result if u.region == filters["region"]]
            if "employment_status" in filters:
                result = [
                    u for u in result
                    if u.employment_status.value == filters["employment_status"]
                ]
        return result

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        result = self.courses
        if filters and "mandatory" in filters:
            result = [c for c in result if c.mandatory == filters["mandatory"]]
        return result

    async def get_enrollments(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[Enrollment]:
        result = self.enrollments
        if user_ids:
            result = [e for e in result if e.user_id in user_ids]
        if course_ids:
            result = [e for e in result if e.course_id in course_ids]
        return result

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        return True
