"""Unit tests for the Blackboard Learn connector."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx
from httpx import Response

from complyos.connectors.blackboard import BlackboardConnector
from complyos.models.domain import EnrollmentStatus, LearningRecordStatus

BASE_URL = "https://blackboard.school.test"
TOKEN_PATH = f"{BASE_URL}/learn/api/public/v1/oauth2/token"
COURSE = "_101_1"


@pytest.fixture
def connector() -> BlackboardConnector:
    return BlackboardConnector(
        base_url=BASE_URL,
        client_id="client-id",
        client_secret="client-secret",
        course_id=COURSE,
    )


def _mock_token() -> None:
    respx.post(TOKEN_PATH).mock(
        return_value=Response(
            200, json={"access_token": "token-1", "token_type": "bearer", "expires_in": 3600}
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_authenticate_uses_basic_auth_client_credentials(
    connector: BlackboardConnector,
) -> None:
    route = respx.post(TOKEN_PATH).mock(
        return_value=Response(200, json={"access_token": "token-1", "expires_in": 3600})
    )

    assert await connector.authenticate() is True
    assert route.called
    request = route.calls.last.request
    expected = base64.b64encode(b"client-id:client-secret").decode()
    assert request.headers["Authorization"] == f"Basic {expected}"
    assert b"grant_type=client_credentials" in request.content


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_authenticate_missing_config_fails_closed() -> None:
    incomplete = BlackboardConnector(base_url=BASE_URL, client_id=None, client_secret=None)

    assert await incomplete.authenticate() is False


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_get_courses_maps_payload(connector: BlackboardConnector) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/learn/api/public/v3/courses").mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "id": "_101_1",
                        "courseId": "TIX-101",
                        "name": "Title IX Training",
                        "description": "Required compliance course",
                        "availability": {"available": "Yes"},
                    }
                ]
            },
        )
    )

    courses = await connector.get_courses()

    assert courses[0].id == "_101_1"
    assert courses[0].code == "TIX-101"
    assert courses[0].title == "Title IX Training"


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_records_normalize_memberships_and_grades(
    connector: BlackboardConnector,
) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/learn/api/public/v1/courses/{COURSE}/users").mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {
                        "userId": "u42",
                        "courseRoleId": "Student",
                        "availability": {"available": "Yes"},
                    },
                    {
                        "userId": "u43",
                        "courseRoleId": "Student",
                        "availability": {"available": "Yes"},
                    },
                ]
            },
        )
    )
    respx.get(f"{BASE_URL}/learn/api/public/v2/courses/{COURSE}/gradebook/columns").mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {"id": "col1", "name": "Final", "grading": {"due": "2026-06-30T23:59:00Z"}}
                ]
            },
        )
    )
    respx.get(
        f"{BASE_URL}/learn/api/public/v2/courses/{COURSE}/gradebook/columns/col1/users"
    ).mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {"userId": "u42", "columnId": "col1", "status": "Graded", "score": 88.0},
                    {"userId": "u43", "columnId": "col1", "status": "NeedsGrading", "exempt": True},
                ]
            },
        )
    )

    records = await connector.get_learning_records()

    by_id = {record.id: record for record in records}

    membership = by_id[f"{COURSE}:u42"]
    assert membership.source_system == "blackboard"
    assert membership.user_id == "u42"
    assert membership.status == LearningRecordStatus.IN_PROGRESS

    graded = by_id[f"{COURSE}:col1:u42"]
    assert graded.status == LearningRecordStatus.COMPLETED
    assert graded.course_id == "col1"  # column id preserved as learning item
    assert graded.score == 88.0
    assert graded.due_date is not None and graded.due_date.isoformat() == "2026-06-30"

    exempt = by_id[f"{COURSE}:col1:u43"]
    assert exempt.status == LearningRecordStatus.EXEMPT
    assert exempt.exempt is True


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_enrollments_compat_layer_maps_status(
    connector: BlackboardConnector,
) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/learn/api/public/v1/courses/{COURSE}/users").mock(
        return_value=Response(
            200,
            json={"results": [{"userId": "u42", "availability": {"available": "Yes"}}]},
        )
    )
    respx.get(f"{BASE_URL}/learn/api/public/v2/courses/{COURSE}/gradebook/columns").mock(
        return_value=Response(200, json={"results": []})
    )

    enrollments = await connector.get_enrollments()

    assert enrollments[0].status == EnrollmentStatus.IN_PROGRESS
    assert enrollments[0].user_id == "u42"


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_follows_next_page_pagination(connector: BlackboardConnector) -> None:
    _mock_token()
    members_path = f"{BASE_URL}/learn/api/public/v1/courses/{COURSE}/users"
    next_rel = f"/learn/api/public/v1/courses/{COURSE}/users?offset=1"
    respx.get(url=f"{BASE_URL}{next_rel}").mock(
        return_value=Response(
            200, json={"results": [{"userId": "u43", "availability": {"available": "Yes"}}]}
        )
    )
    respx.get(members_path).mock(
        return_value=Response(
            200,
            json={
                "results": [{"userId": "u42", "availability": {"available": "Yes"}}],
                "paging": {"nextPage": next_rel},
            },
        )
    )
    respx.get(f"{BASE_URL}/learn/api/public/v2/courses/{COURSE}/gradebook/columns").mock(
        return_value=Response(200, json={"results": []})
    )

    records = await connector.get_learning_records()

    assert {record.user_id for record in records} == {"u42", "u43"}


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_http_error_fails_closed(connector: BlackboardConnector) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/learn/api/public/v1/courses/{COURSE}/users").mock(
        return_value=Response(401, json={"status": 401, "message": "Unauthorized"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await connector.get_learning_records()


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_auth_failure_during_pull_fails_closed(
    connector: BlackboardConnector,
) -> None:
    respx.post(TOKEN_PATH).mock(return_value=Response(401, json={"error": "invalid_client"}))

    with pytest.raises(httpx.HTTPStatusError):
        await connector.get_learning_records()


@pytest.mark.asyncio
@respx.mock
async def test_blackboard_malformed_payload_does_not_crash(
    connector: BlackboardConnector,
) -> None:
    _mock_token()
    respx.get(f"{BASE_URL}/learn/api/public/v1/courses/{COURSE}/users").mock(
        return_value=Response(200, json={"results": []})
    )
    respx.get(f"{BASE_URL}/learn/api/public/v2/courses/{COURSE}/gradebook/columns").mock(
        return_value=Response(200, json={"results": [{"id": "col1"}]})
    )
    respx.get(
        f"{BASE_URL}/learn/api/public/v2/courses/{COURSE}/gradebook/columns/col1/users"
    ).mock(
        return_value=Response(
            200,
            json={"results": [{"userId": "u42", "status": "garbage", "score": "n/a"}]},
        )
    )

    records = await connector.get_learning_records()

    assert records[0].status == LearningRecordStatus.ASSIGNED
    assert records[0].score is None


@pytest.mark.asyncio
async def test_blackboard_learning_records_require_course_scope() -> None:
    scopeless = BlackboardConnector(base_url=BASE_URL, client_id="id", client_secret="secret")

    with pytest.raises(ValueError, match="course scope"):
        await scopeless.get_learning_records()


@pytest.mark.asyncio
async def test_blackboard_trigger_reminder_is_read_only(connector: BlackboardConnector) -> None:
    assert await connector.trigger_reminder("u42", "col1") is False
