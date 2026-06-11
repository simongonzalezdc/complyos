"""Unit tests for SAP SuccessFactors Learning connector."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from complyos.connectors.successfactors import SuccessFactorsConnector
from complyos.models.domain import EnrollmentStatus, LearningRecordStatus


@pytest.fixture
def connector() -> SuccessFactorsConnector:
    return SuccessFactorsConnector(
        base_url="https://acme-learning.successfactors.test",
        client_id="client-id",
        client_secret="client-secret",
        company_id="tenant",
        user_id="api-admin",
    )


@pytest.mark.asyncio
@respx.mock
async def test_successfactors_authenticate_uses_oauth_token(connector: SuccessFactorsConnector):
    route = respx.post(
        "https://acme-learning.successfactors.test/learning/oauth-api/rest/v1/token"
    ).mock(return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600}))

    assert await connector.authenticate() is True
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_successfactors_get_users_maps_odata_payload(connector: SuccessFactorsConnector):
    respx.post("https://acme-learning.successfactors.test/learning/oauth-api/rest/v1/token").mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )
    respx.get(
        "https://acme-learning.successfactors.test/learning/odatav4/public/admin/user-service/v1/Users"
    ).mock(
        return_value=Response(
            200,
            json={
                "value": [
                    {
                        "userID": "u1",
                        "emailAddress": "learner@example.com",
                        "fname": "Ada",
                        "lname": "Lovelace",
                        "departmentID": "Engineering",
                        "regionID": "US",
                        "hireDate": "2022-01-15",
                        "status": "active",
                    }
                ]
            },
        )
    )

    users = await connector.get_users()

    assert users[0].id == "u1"
    assert users[0].first_name == "Ada"
    assert users[0].department == "Engineering"


@pytest.mark.asyncio
@respx.mock
async def test_successfactors_learning_history_maps_records_and_enrollments(
    connector: SuccessFactorsConnector,
):
    respx.post("https://acme-learning.successfactors.test/learning/oauth-api/rest/v1/token").mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )
    respx.get(
        "https://acme-learning.successfactors.test/learning/odatav4/public/user/userlearning-service/v1/LearningHistory"
    ).mock(
        return_value=Response(
            200,
            json={
                "value": [
                    {
                        "recordID": "lh1",
                        "userID": "u1",
                        "componentID": "course-1",
                        "componentTitle": "Safety Basics",
                        "completionStatusID": "COMPLETE",
                        "completionDate": "2026-05-01T10:00:00Z",
                        "grade": 96,
                    }
                ]
            },
        )
    )

    records = await connector.get_learning_records()
    enrollments = await connector.get_enrollments()

    assert records[0].id == "lh1"
    assert records[0].status == LearningRecordStatus.COMPLETED
    assert records[0].score == 96
    assert enrollments[0].status == EnrollmentStatus.COMPLETED
