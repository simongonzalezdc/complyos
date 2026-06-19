"""Unit tests for the D2L Brightspace (Valence) connector."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from complyos.connectors.brightspace import BrightspaceConnector
from complyos.models.domain import EnrollmentStatus, LearningRecordStatus

BASE_URL = "https://school.brightspace.test"
TOKEN_URL = "https://auth.brightspace.test/core/connect/token"
LP = "1.49"
LE = "1.82"


@pytest.fixture
def connector() -> BrightspaceConnector:
    return BrightspaceConnector(
        base_url=BASE_URL,
        client_id="client-id",
        client_secret="client-secret",
        token_url=TOKEN_URL,
        org_unit_id="6606",
    )


def _mock_token() -> None:
    respx.post(TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_authenticate_uses_client_credentials(
    connector: BrightspaceConnector,
) -> None:
    route = respx.post(TOKEN_URL).mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )

    assert await connector.authenticate() is True
    assert route.called
    sent = route.calls.last.request.content.decode()
    assert "grant_type=client_credentials" in sent
    assert "client_id=client-id" in sent


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_authenticate_missing_config_fails_closed() -> None:
    incomplete = BrightspaceConnector(base_url=BASE_URL, client_id=None, client_secret=None)

    assert await incomplete.authenticate() is False


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_records_join_enrollments_and_final_grades(
    connector: BrightspaceConnector,
) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/d2l/api/lp/{LP}/enrollments/orgUnits/6606/users/").mock(
        return_value=Response(
            200,
            json={
                "PagingInfo": {"Bookmark": "", "HasMoreItems": False},
                "Items": [
                    {
                        "User": {
                            "Identifier": "42",
                            "DisplayName": "Ada Lovelace",
                            "EmailAddress": "ada@example.com",
                            "OrgDefinedId": "S-42",
                        },
                        "Role": {"Id": "110", "Name": "Learner"},
                        "OrgUnitId": 6606,
                        "IsCompleted": True,
                        "CompletionDate": "2026-05-01T10:00:00Z",
                    }
                ],
            },
        )
    )
    respx.get(f"{BASE_URL}/d2l/api/le/{LE}/6606/grades/final/values/").mock(
        return_value=Response(
            200,
            json={
                "PagingInfo": {"Bookmark": "", "HasMoreItems": False},
                "Items": [
                    {
                        "UserId": "42",
                        "DisplayedGrade": "91.5",
                        "PointsNumerator": 91.5,
                        "PointsDenominator": 100.0,
                    }
                ],
            },
        )
    )

    records = await connector.get_learning_records()

    assert len(records) == 1
    record = records[0]
    assert record.source_system == "brightspace"
    assert record.user_id == "42"
    assert record.course_id == "6606"
    assert record.status == LearningRecordStatus.COMPLETED
    assert record.score == 91.5
    assert record.completed_date is not None
    assert record.source_payload["FinalGrade"]["DisplayedGrade"] == "91.5"


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_enrollments_compat_layer_maps_status(
    connector: BrightspaceConnector,
) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/d2l/api/lp/{LP}/enrollments/orgUnits/6606/users/").mock(
        return_value=Response(
            200,
            json={
                "PagingInfo": {"Bookmark": "", "HasMoreItems": False},
                "Items": [
                    {
                        "User": {"Identifier": "43", "DisplayName": "In Progress"},
                        "OrgUnitId": 6606,
                        "Access": {"IsActive": True},
                    }
                ],
            },
        )
    )
    respx.get(f"{BASE_URL}/d2l/api/le/{LE}/6606/grades/final/values/").mock(
        return_value=Response(200, json={"PagingInfo": {"HasMoreItems": False}, "Items": []})
    )

    enrollments = await connector.get_enrollments()

    assert enrollments[0].status == EnrollmentStatus.IN_PROGRESS
    assert enrollments[0].user_id == "43"


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_follows_bookmark_pagination(connector: BrightspaceConnector) -> None:
    _mock_token()
    enroll_path = f"{BASE_URL}/d2l/api/lp/{LP}/enrollments/orgUnits/6606/users/"
    page2 = f"{enroll_path}?bookmark=42"
    respx.get(url=page2).mock(
        return_value=Response(
            200,
            json={
                "PagingInfo": {"Bookmark": "43", "HasMoreItems": False},
                "Items": [{"User": {"Identifier": "43", "DisplayName": "Two"}}],
            },
        )
    )
    respx.get(enroll_path).mock(
        return_value=Response(
            200,
            json={
                "PagingInfo": {"Bookmark": "42", "HasMoreItems": True},
                "Items": [{"User": {"Identifier": "42", "DisplayName": "One"}}],
            },
        )
    )
    respx.get(f"{BASE_URL}/d2l/api/le/{LE}/6606/grades/final/values/").mock(
        return_value=Response(200, json={"PagingInfo": {"HasMoreItems": False}, "Items": []})
    )

    records = await connector.get_learning_records()

    assert {record.user_id for record in records} == {"42", "43"}


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_http_error_fails_closed(connector: BrightspaceConnector) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/d2l/api/lp/{LP}/enrollments/orgUnits/6606/users/").mock(
        return_value=Response(403, json={"Errors": [{"Message": "Not authorized"}]})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await connector.get_learning_records()


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_auth_failure_during_pull_fails_closed(
    connector: BrightspaceConnector,
) -> None:
    respx.post(TOKEN_URL).mock(return_value=Response(401, json={"error": "invalid_client"}))

    with pytest.raises(httpx.HTTPStatusError):
        await connector.get_learning_records()


@pytest.mark.asyncio
@respx.mock
async def test_brightspace_malformed_payload_does_not_crash(
    connector: BrightspaceConnector,
) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/d2l/api/lp/{LP}/enrollments/orgUnits/6606/users/").mock(
        return_value=Response(
            200,
            json={
                "PagingInfo": {"HasMoreItems": False},
                "Items": [{"User": {"Identifier": "42"}, "OrgUnitId": 6606}],
            },
        )
    )
    respx.get(f"{BASE_URL}/d2l/api/le/{LE}/6606/grades/final/values/").mock(
        return_value=Response(
            200,
            json={
                "PagingInfo": {"HasMoreItems": False},
                "Items": [{"UserId": "42", "DisplayedGrade": "n/a", "PointsDenominator": 0}],
            },
        )
    )

    records = await connector.get_learning_records()

    assert records[0].status == LearningRecordStatus.IN_PROGRESS
    assert records[0].score is None


@pytest.mark.asyncio
async def test_brightspace_learning_records_require_course_scope() -> None:
    scopeless = BrightspaceConnector(
        base_url=BASE_URL, client_id="id", client_secret="secret", token_url=TOKEN_URL
    )

    with pytest.raises(ValueError, match="course"):
        await scopeless.get_learning_records()


@pytest.mark.asyncio
async def test_brightspace_trigger_reminder_is_read_only(connector: BrightspaceConnector) -> None:
    assert await connector.trigger_reminder("42", "6606") is False
