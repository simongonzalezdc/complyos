"""Unit tests for the mock connector."""

from __future__ import annotations

from complyos.connectors.mock import MockConnector
from complyos.models.domain import EmploymentStatus


class TestMockConnector:
    async def test_seed_data_present(self):
        conn = MockConnector()
        assert len(conn.users) == 5
        assert len(conn.courses) == 3
        assert len(conn.enrollments) == 3

    async def test_authenticate_always_true(self):
        conn = MockConnector()
        assert await conn.authenticate() is True

    async def test_get_users_no_filter(self):
        conn = MockConnector()
        users = await conn.get_users()
        assert len(users) == 5

    async def test_get_users_filter_by_department(self):
        conn = MockConnector()
        users = await conn.get_users(filters={"department": "Engineering"})
        assert len(users) == 3  # Alice, Bob, Eve
        assert all(u.department == "Engineering" for u in users)

    async def test_get_users_filter_by_region(self):
        conn = MockConnector()
        users = await conn.get_users(filters={"region": "MX"})
        assert len(users) == 1
        assert users[0].region == "MX"

    async def test_get_users_filter_by_status(self):
        conn = MockConnector()
        users = await conn.get_users(filters={"employment_status": "terminated"})
        assert len(users) == 1
        assert users[0].employment_status == EmploymentStatus.TERMINATED

    async def test_get_courses_filter_mandatory(self):
        conn = MockConnector()
        courses = await conn.get_courses(filters={"mandatory": True})
        assert len(courses) == 2  # Respectful Environment, Security
        assert all(c.mandatory for c in courses)

    async def test_get_enrollments_filter_by_user(self):
        conn = MockConnector()
        enrollments = await conn.get_enrollments(user_ids=["u1"])
        assert len(enrollments) == 1
        assert enrollments[0].user_id == "u1"

    async def test_get_enrollments_filter_by_course(self):
        conn = MockConnector()
        enrollments = await conn.get_enrollments(course_ids=["c1"])
        assert len(enrollments) == 3  # Alice, Bob, David all have respect enrollments

    async def test_trigger_reminder(self):
        conn = MockConnector()
        assert await conn.trigger_reminder("u1", "c1") is True


async def test_default_get_learning_records_maps_enrollments():
    conn = MockConnector()

    records = await conn.get_learning_records()
    enrollments = await conn.get_enrollments()

    assert records
    assert all(record.source_system == "mock" for record in records)
    assert [record.id for record in records] == [enrollment.id for enrollment in enrollments]
