"""Unit tests for Workday connector with mocked HTTP responses."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from complyos.connectors.workday import WorkdayConnector
from complyos.models.domain import EmploymentStatus, EnrollmentStatus


@pytest.fixture
def connector() -> WorkdayConnector:
    return WorkdayConnector(
        base_url="https://wd2-impl-services1.workday.com/test",
        username="test_user",
        password="test_pass",
    )


class TestWorkdayConnector:
    @respx.mock
    async def test_authenticate_success(self, connector: WorkdayConnector):
        route = respx.get("https://wd2-impl-services1.workday.com/test/learning/v1/workers").mock(
            return_value=Response(200, json={"data": []})
        )
        result = await connector.authenticate()
        assert result is True
        assert route.called

    @respx.mock
    async def test_authenticate_failure(self, connector: WorkdayConnector):
        respx.get("https://wd2-impl-services1.workday.com/test/learning/v1/workers").mock(
            return_value=Response(401, json={"error": "Unauthorized"})
        )
        result = await connector.authenticate()
        assert result is False

    @respx.mock
    async def test_get_users(self, connector: WorkdayConnector):
        respx.get("https://wd2-impl-services1.workday.com/test/learning/v1/workers").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "w1",
                        "employeeID": "E001",
                        "firstName": "Alice",
                        "lastName": "Smith",
                        "primaryWorkEmail": "alice@example.com",
                        "supervisoryOrganization": {"descriptor": "Engineering"},
                        "location": {"descriptor": "US"},
                        "hireDate": "2020-01-15",
                        "workerStatus": "Active",
                    }
                ]
            })
        )
        users = await connector.get_users()
        assert len(users) == 1
        assert users[0].id == "w1"
        assert users[0].first_name == "Alice"
        assert users[0].employment_status == EmploymentStatus.ACTIVE

    @respx.mock
    async def test_get_courses(self, connector: WorkdayConnector):
        respx.get("https://wd2-impl-services1.workday.com/test/learning/v1/courses").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "c1",
                        "courseNumber": "RESPECT-101",
                        "title": "Respectful Environment",
                        "required": True,
                    }
                ]
            })
        )
        courses = await connector.get_courses()
        assert len(courses) == 1
        assert courses[0].code == "RESPECT-101"
        assert courses[0].mandatory is True

    @respx.mock
    async def test_get_enrollments(self, connector: WorkdayConnector):
        respx.get("https://wd2-impl-services1.workday.com/test/learning/v1/enrollments").mock(
            return_value=Response(200, json={
                "data": [
                    {
                        "id": "e1",
                        "worker": {"id": "w1"},
                        "course": {"id": "c1"},
                        "status": "Completed",
                        "percentComplete": 100,
                    }
                ]
            })
        )
        enrollments = await connector.get_enrollments()
        assert len(enrollments) == 1
        assert enrollments[0].user_id == "w1"
        assert enrollments[0].status == EnrollmentStatus.COMPLETED

    @respx.mock
    async def test_trigger_reminder(self, connector: WorkdayConnector):
        respx.post("https://wd2-impl-services1.workday.com/test/learning/v1/notifications").mock(
            return_value=Response(201, json={"id": "n1"})
        )
        result = await connector.trigger_reminder("w1", "c1")
        assert result is True
