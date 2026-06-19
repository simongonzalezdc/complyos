"""Unit tests for the Canvas LMS connector."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from complyos.connectors.canvas import CanvasConnector
from complyos.models.domain import EnrollmentStatus, LearningRecordStatus

BASE_URL = "https://school.instructure.test"


@pytest.fixture
def connector() -> CanvasConnector:
    return CanvasConnector(
        base_url=BASE_URL,
        api_token="test-token",
        course_id="101",
    )


@pytest.mark.asyncio
@respx.mock
async def test_canvas_authenticate_sends_bearer_token(connector: CanvasConnector) -> None:
    route = respx.get(f"{BASE_URL}/api/v1/users/self").mock(
        return_value=Response(200, json={"id": 1})
    )

    assert await connector.authenticate() is True
    assert route.called
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
@respx.mock
async def test_canvas_authenticate_missing_config_fails_closed() -> None:
    incomplete = CanvasConnector(base_url="", api_token=None)

    assert await incomplete.authenticate() is False


@pytest.mark.asyncio
@respx.mock
async def test_canvas_get_courses_maps_account_courses(connector: CanvasConnector) -> None:
    respx.get(f"{BASE_URL}/api/v1/accounts/self/courses").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": 101,
                    "name": "Title IX Training",
                    "course_code": "TIX-101",
                    "public_description": "Required compliance course",
                }
            ],
        )
    )

    courses = await connector.get_courses()

    assert courses[0].id == "101"
    assert courses[0].code == "TIX-101"
    assert courses[0].title == "Title IX Training"


@pytest.mark.asyncio
@respx.mock
async def test_canvas_records_normalize_enrollments_and_submissions(
    connector: CanvasConnector,
) -> None:
    respx.get(f"{BASE_URL}/api/v1/courses/101/enrollments").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": 5001,
                    "user_id": 42,
                    "course_id": 101,
                    "type": "StudentEnrollment",
                    "enrollment_state": "completed",
                    "created_at": "2026-01-10T08:00:00Z",
                    "grades": {"current_score": 91.5, "final_score": 91.5},
                }
            ],
        )
    )
    respx.get(f"{BASE_URL}/api/v1/courses/101/students/submissions").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": 7001,
                    "user_id": 42,
                    "assignment_id": 900,
                    "workflow_state": "graded",
                    "score": 88.0,
                    "submitted_at": "2026-06-01T09:00:00Z",
                    "cached_due_date": "2026-06-30T23:59:00Z",
                    "excused": False,
                },
                {
                    "id": 7002,
                    "user_id": 43,
                    "assignment_id": 900,
                    "workflow_state": "unsubmitted",
                    "excused": True,
                    "cached_due_date": "2026-06-30T23:59:00Z",
                },
            ],
        )
    )

    records = await connector.get_learning_records()

    by_id = {record.id: record for record in records}
    enrollment_record = by_id["5001"]
    assert enrollment_record.source_system == "canvas"
    assert enrollment_record.user_id == "42"
    assert enrollment_record.course_id == "101"
    assert enrollment_record.status == LearningRecordStatus.COMPLETED
    assert enrollment_record.score == 91.5
    assert enrollment_record.source_payload["type"] == "StudentEnrollment"

    graded = by_id["7001"]
    assert graded.status == LearningRecordStatus.COMPLETED
    assert graded.course_id == "900"  # assignment id preserved as learning item
    assert graded.score == 88.0
    assert graded.due_date is not None and graded.due_date.isoformat() == "2026-06-30"

    excused = by_id["7002"]
    assert excused.status == LearningRecordStatus.EXEMPT
    assert excused.exempt is True


@pytest.mark.asyncio
@respx.mock
async def test_canvas_enrollments_compat_layer_maps_to_enrollment_status(
    connector: CanvasConnector,
) -> None:
    respx.get(f"{BASE_URL}/api/v1/courses/101/enrollments").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": 5001,
                    "user_id": 42,
                    "course_id": 101,
                    "enrollment_state": "active",
                }
            ],
        )
    )
    respx.get(f"{BASE_URL}/api/v1/courses/101/students/submissions").mock(
        return_value=Response(200, json=[])
    )

    enrollments = await connector.get_enrollments()

    assert enrollments[0].status == EnrollmentStatus.IN_PROGRESS
    assert enrollments[0].user_id == "42"


@pytest.mark.asyncio
@respx.mock
async def test_canvas_follows_link_header_pagination(connector: CanvasConnector) -> None:
    enroll_path = f"{BASE_URL}/api/v1/courses/101/enrollments"
    page2 = f"{enroll_path}?page=2"
    # Register the page-2 route (with query) first so respx matches it before the
    # query-agnostic page-1 route when the connector follows the next link.
    respx.get(url=page2).mock(
        return_value=Response(
            200,
            json=[{"id": 2, "user_id": 2, "course_id": 101, "enrollment_state": "active"}],
        )
    )
    respx.get(enroll_path).mock(
        return_value=Response(
            200,
            json=[{"id": 1, "user_id": 1, "course_id": 101, "enrollment_state": "active"}],
            headers={"Link": f'<{page2}>; rel="next", <{enroll_path}>; rel="first"'},
        )
    )
    respx.get(f"{BASE_URL}/api/v1/courses/101/students/submissions").mock(
        return_value=Response(200, json=[])
    )

    records = await connector.get_learning_records()

    assert {record.id for record in records} == {"1", "2"}


@pytest.mark.asyncio
@respx.mock
async def test_canvas_http_error_fails_closed(connector: CanvasConnector) -> None:
    respx.get(f"{BASE_URL}/api/v1/courses/101/enrollments").mock(
        return_value=Response(401, json={"errors": [{"message": "Invalid access token."}]})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await connector.get_learning_records()


@pytest.mark.asyncio
@respx.mock
async def test_canvas_malformed_payload_does_not_crash(connector: CanvasConnector) -> None:
    respx.get(f"{BASE_URL}/api/v1/courses/101/enrollments").mock(
        return_value=Response(200, json="not-a-list")
    )
    respx.get(f"{BASE_URL}/api/v1/courses/101/students/submissions").mock(
        return_value=Response(
            200,
            json=[{"id": 7001, "user_id": None, "workflow_state": "garbage", "score": "n/a"}],
        )
    )

    records = await connector.get_learning_records()

    # Malformed enrollment payload yields no records; the bad submission still
    # normalizes to a safe ASSIGNED record without raising.
    assert [record.id for record in records] == ["7001"]
    assert records[0].status == LearningRecordStatus.ASSIGNED
    assert records[0].score is None


@pytest.mark.asyncio
async def test_canvas_learning_records_require_course_scope() -> None:
    scopeless = CanvasConnector(base_url=BASE_URL, api_token="test-token")

    with pytest.raises(ValueError, match="course scope"):
        await scopeless.get_learning_records()


@pytest.mark.asyncio
async def test_canvas_trigger_reminder_is_read_only(connector: CanvasConnector) -> None:
    assert await connector.trigger_reminder("42", "900") is False
