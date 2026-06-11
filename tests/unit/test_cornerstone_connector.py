"""Unit tests for Cornerstone Learning connector."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from complyos.connectors.cornerstone import CornerstoneConnector
from complyos.models.domain import EnrollmentStatus, LearningRecordStatus


@pytest.fixture
def connector() -> CornerstoneConnector:
    return CornerstoneConnector(
        base_url="https://tenant.csod.test",
        client_id="client-id",
        client_secret="client-secret",
    )


@pytest.mark.asyncio
@respx.mock
async def test_cornerstone_authenticate_uses_client_credentials(connector: CornerstoneConnector):
    route = respx.post("https://tenant.csod.test/services/api/oauth2/token").mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )

    assert await connector.authenticate() is True
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_cornerstone_get_courses_maps_learning_objects(connector: CornerstoneConnector):
    respx.post("https://tenant.csod.test/services/api/oauth2/token").mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )
    respx.get("https://tenant.csod.test/services/api/x/learning/v1/learning-objects").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "id": "lo-1",
                        "locator": "SEC-101",
                        "title": "Security Annual",
                        "description": "Annual security course",
                        "duration": 45,
                        "isRequired": True,
                    }
                ]
            },
        )
    )

    courses = await connector.get_courses()

    assert courses[0].id == "lo-1"
    assert courses[0].code == "SEC-101"
    assert courses[0].mandatory is True


@pytest.mark.asyncio
@respx.mock
async def test_cornerstone_transcripts_map_records_and_enrollments(connector: CornerstoneConnector):
    respx.post("https://tenant.csod.test/services/api/oauth2/token").mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )
    respx.get("https://tenant.csod.test/services/api/x/learning/v1/transcripts").mock(
        return_value=Response(
            200,
            json={
                "data": [
                    {
                        "transcriptId": "t1",
                        "userId": "u1",
                        "loId": "lo-1",
                        "title": "Security Annual",
                        "status": "Completed",
                        "dueDate": "2026-06-30",
                        "completionDate": "2026-06-01T09:00:00Z",
                        "score": 88,
                    }
                ]
            },
        )
    )

    records = await connector.get_learning_records()
    enrollments = await connector.get_enrollments()

    assert records[0].id == "t1"
    assert records[0].status == LearningRecordStatus.COMPLETED
    assert records[0].score == 88
    assert enrollments[0].status == EnrollmentStatus.COMPLETED
