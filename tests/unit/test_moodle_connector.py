"""Unit tests for the Moodle Web Services connector."""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from complyos.connectors.moodle import MoodleConnector, MoodleWebServiceError
from complyos.models.domain import EnrollmentStatus, LearningRecordStatus

BASE_URL = "https://moodle.school.test"
REST = f"{BASE_URL}/webservice/rest/server.php"


@pytest.fixture
def connector() -> MoodleConnector:
    return MoodleConnector(base_url=BASE_URL, token="test-token", course_id="7")


def _wsfunction(request: httpx.Request) -> str:
    return request.url.params.get("wsfunction", "")


@pytest.mark.asyncio
@respx.mock
async def test_moodle_authenticate_validates_token_via_site_info(
    connector: MoodleConnector,
) -> None:
    route = respx.get(REST).mock(
        return_value=Response(200, json={"sitename": "Test", "userid": 2})
    )

    assert await connector.authenticate() is True
    assert route.called
    last = route.calls.last.request
    assert last.url.params["wstoken"] == "test-token"
    assert last.url.params["moodlewsrestformat"] == "json"
    assert _wsfunction(last) == "core_webservice_get_site_info"


@pytest.mark.asyncio
@respx.mock
async def test_moodle_authenticate_missing_config_fails_closed() -> None:
    incomplete = MoodleConnector(base_url="", token=None)

    assert await incomplete.authenticate() is False


@pytest.mark.asyncio
@respx.mock
async def test_moodle_get_courses_maps_payload(connector: MoodleConnector) -> None:
    respx.get(REST).mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": 7,
                    "shortname": "TIX-101",
                    "fullname": "Title IX Training",
                    "summary": "<p>Required course</p>",
                    "format": "topics",
                }
            ],
        )
    )

    courses = await connector.get_courses()

    assert courses[0].id == "7"
    assert courses[0].code == "TIX-101"
    assert courses[0].title == "Title IX Training"
    assert courses[0].category == "topics"


@pytest.mark.asyncio
@respx.mock
async def test_moodle_records_join_roster_and_completion(connector: MoodleConnector) -> None:
    def handler(request: httpx.Request) -> Response:
        fn = _wsfunction(request)
        if fn == "core_enrol_get_enrolled_users":
            return Response(
                200,
                json=[
                    {
                        "id": 42,
                        "username": "ada",
                        "firstname": "Ada",
                        "lastname": "Lovelace",
                        "email": "ada@example.com",
                        "fullname": "Ada Lovelace",
                    },
                    {
                        "id": 43,
                        "username": "grace",
                        "firstname": "Grace",
                        "lastname": "Hopper",
                        "fullname": "Grace Hopper",
                    },
                ],
            )
        if fn == "core_completion_get_course_completion_status":
            userid = request.url.params.get("userid")
            completed = userid == "42"
            return Response(
                200,
                json={
                    "completionstatus": {
                        "completed": completed,
                        "completions": (
                            [{"type": 4, "complete": True, "timecompleted": 1717200000}]
                            if completed
                            else [{"type": 4, "complete": False, "timecompleted": 0}]
                        ),
                    }
                },
            )
        return Response(200, json=[])

    respx.get(REST).mock(side_effect=handler)

    records = await connector.get_learning_records()

    by_user = {record.user_id: record for record in records}
    assert by_user["42"].source_system == "moodle"
    assert by_user["42"].course_id == "7"
    assert by_user["42"].status == LearningRecordStatus.COMPLETED
    assert by_user["42"].completed_date is not None
    assert by_user["43"].status == LearningRecordStatus.IN_PROGRESS
    assert by_user["43"].completed_date is None


@pytest.mark.asyncio
@respx.mock
async def test_moodle_enrollments_compat_layer_maps_status(connector: MoodleConnector) -> None:
    def handler(request: httpx.Request) -> Response:
        fn = _wsfunction(request)
        if fn == "core_enrol_get_enrolled_users":
            return Response(200, json=[{"id": 42, "fullname": "Ada Lovelace"}])
        if fn == "core_completion_get_course_completion_status":
            return Response(200, json={"completionstatus": {"completed": True, "completions": []}})
        return Response(200, json=[])

    respx.get(REST).mock(side_effect=handler)

    enrollments = await connector.get_enrollments()

    assert enrollments[0].status == EnrollmentStatus.COMPLETED
    assert enrollments[0].user_id == "42"


@pytest.mark.asyncio
@respx.mock
async def test_moodle_completion_disabled_is_not_a_failure(connector: MoodleConnector) -> None:
    def handler(request: httpx.Request) -> Response:
        fn = _wsfunction(request)
        if fn == "core_enrol_get_enrolled_users":
            return Response(200, json=[{"id": 42, "fullname": "Ada Lovelace"}])
        if fn == "core_completion_get_course_completion_status":
            return Response(
                200,
                json={
                    "exception": "moodle_exception",
                    "errorcode": "errorcoursecompletionnotenabled",
                    "message": "Course completion is not enabled",
                },
            )
        return Response(200, json=[])

    respx.get(REST).mock(side_effect=handler)

    records = await connector.get_learning_records()

    # Completion not enabled => not applicable, learner still surfaces in progress.
    assert records[0].status == LearningRecordStatus.IN_PROGRESS


@pytest.mark.asyncio
@respx.mock
async def test_moodle_error_body_fails_closed(connector: MoodleConnector) -> None:
    # Moodle returns HTTP 200 with an exception body for auth/permission failures.
    respx.get(REST).mock(
        return_value=Response(
            200,
            json={
                "exception": "webservice_access_exception",
                "errorcode": "accessexception",
                "message": "Access control exception",
            },
        )
    )

    with pytest.raises(MoodleWebServiceError, match="accessexception"):
        await connector.get_learning_records()


@pytest.mark.asyncio
@respx.mock
async def test_moodle_http_error_fails_closed(connector: MoodleConnector) -> None:
    respx.get(REST).mock(return_value=Response(500, text="server error"))

    with pytest.raises(httpx.HTTPStatusError):
        await connector.get_learning_records()


@pytest.mark.asyncio
@respx.mock
async def test_moodle_malformed_payload_does_not_crash(connector: MoodleConnector) -> None:
    def handler(request: httpx.Request) -> Response:
        fn = _wsfunction(request)
        if fn == "core_enrol_get_enrolled_users":
            return Response(200, json=[{"id": 42}, "garbage", {"id": None}])
        if fn == "core_completion_get_course_completion_status":
            return Response(200, json={"completionstatus": "not-a-dict"})
        return Response(200, json=[])

    respx.get(REST).mock(side_effect=handler)

    records = await connector.get_learning_records()

    # The string item is dropped; the two dict users still normalize safely.
    assert {record.user_id for record in records} == {"42", ""}
    assert all(record.status == LearningRecordStatus.IN_PROGRESS for record in records)


@pytest.mark.asyncio
async def test_moodle_learning_records_require_course_scope() -> None:
    scopeless = MoodleConnector(base_url=BASE_URL, token="test-token")

    with pytest.raises(ValueError, match="course scope"):
        await scopeless.get_learning_records()


@pytest.mark.asyncio
async def test_moodle_trigger_reminder_is_read_only(connector: MoodleConnector) -> None:
    assert await connector.trigger_reminder("42", "7") is False
