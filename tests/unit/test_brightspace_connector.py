"""Unit tests for the D2L Brightspace (Valence) connector."""

from __future__ import annotations

import socket

import httpx
import pytest
import respx
from httpx import Response

from complyos.connectors.base import ConnectorConfigurationError
from complyos.connectors.brightspace import BrightspaceConnector
from complyos.models.domain import EnrollmentStatus, LearningRecordStatus

BASE_URL = "https://school.brightspace.test"
TOKEN_URL = "https://auth.brightspace.test/core/connect/token"
LP = "1.49"
LE = "1.82"


class _SocketGuard:
    """Fail-loud guard proving a code path never reaches the network layer.

    DNS resolution and TCP connects are recorded and raise immediately, so a
    regression that dials out (e.g. to the real auth.brightspace.com) cannot
    silently pass — it either trips the guard's AssertionError or shows up in
    ``attempts`` and fails the zero-attempts assertion.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.attempts: list[str] = []
        for name in ("getaddrinfo", "create_connection"):
            monkeypatch.setattr(
                socket,
                name,
                lambda *a, _n=name, **kw: self._forbid(_n, *a, **kw),
            )
        monkeypatch.setattr(
            socket.socket,
            "connect",
            lambda self_, address: self._forbid("socket.connect", address),
        )

    def _forbid(self, what: str, *args: object, **kwargs: object) -> None:
        detail = " ".join(str(a) for a in args[:2])
        self.attempts.append(f"{what}({detail})")
        raise AssertionError(f"network egress attempted during fail-closed path: {what} {detail}")


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


def test_brightspace_credentials_without_token_url_fail_closed_before_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adversary caveat 2 (2026-09-19): creds + no token_url must NEVER dial.

    The old code silently fell back to the hardcoded real
    auth.brightspace.com endpoint; the fix must raise a structured
    configuration error at construction — before any socket exists. The socket
    guard makes any egress attempt (DNS or TCP, including to the real host)
    fail the test loudly.
    """
    guard = _SocketGuard(monkeypatch)
    monkeypatch.delenv("BRIGHTSPACE_TOKEN_URL", raising=False)

    with pytest.raises(ConnectorConfigurationError) as excinfo:
        BrightspaceConnector(
            base_url=BASE_URL, client_id="fake-id", client_secret="fake-secret"
        )

    message = str(excinfo.value)
    assert "token_url" in message
    assert "BRIGHTSPACE_TOKEN_URL" in message
    assert "no network request was made" in message
    assert guard.attempts == []


@pytest.mark.asyncio
async def test_brightspace_env_credentials_without_token_url_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env-var credentials follow the same fail-closed rule as config creds."""
    guard = _SocketGuard(monkeypatch)
    monkeypatch.setenv("BRIGHTSPACE_BASE_URL", BASE_URL)
    monkeypatch.setenv("BRIGHTSPACE_CLIENT_ID", "fake-id")
    monkeypatch.setenv("BRIGHTSPACE_CLIENT_SECRET", "fake-secret")
    monkeypatch.delenv("BRIGHTSPACE_TOKEN_URL", raising=False)

    with pytest.raises(ConnectorConfigurationError):
        BrightspaceConnector()

    assert guard.attempts == []


def test_brightspace_explicit_token_url_constructs_without_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit token_url keeps the connector usable — fail-closed, not broken."""
    monkeypatch.delenv("BRIGHTSPACE_TOKEN_URL", raising=False)

    connector = BrightspaceConnector(
        base_url=BASE_URL,
        client_id="client-id",
        client_secret="client-secret",
        token_url=TOKEN_URL,
    )

    assert connector.token_url == TOKEN_URL


@pytest.mark.asyncio
async def test_brightspace_token_fetch_never_dials_without_explicit_token_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defense in depth: ``_token()`` re-checks token_url before the POST.

    Covers attribute mutation after construction (bypassing the __init__
    guard): the token fetch must raise the structured error, and health_check
    must surface it as a clean auth failure — with zero socket attempts.
    """
    guard = _SocketGuard(monkeypatch)
    connector = BrightspaceConnector(
        base_url=BASE_URL,
        client_id="client-id",
        client_secret="client-secret",
        token_url=TOKEN_URL,
    )
    connector.token_url = None  # simulate a bypassed/mutated configuration

    with pytest.raises(ConnectorConfigurationError):
        await connector._token()

    health = await connector.health_check()
    assert health["status"] in ("auth_failed", "error")
    assert health["authenticated"] is False
    assert guard.attempts == []
