"""Rate-limit tests for remote mutating API v1 endpoints (WP12b / plan §8.1, §8.3).

Deployment posture is customer-hosted / local-first single-tenant, so the limiter
is an in-process fixed-window counter (no Redis). These tests verify:

- A low configured limit eventually returns 429 on repeated mutating POSTs.
- Requests under the limit succeed.
- The 429 body uses the project structured-error shape and a Retry-After header.
- With the limiter unset (default), many mutating requests succeed (no false trips).
- Read-only GETs are not rate-limited.

Limiter state is process-global, so each test resets it via ``reset_rate_limiter``
to stay isolated and avoid bleed between cases.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from complyos.core.repository import LocalRepository
from complyos.web.api_v1 import create_api_v1_app
from complyos.web.rate_limit import reset_rate_limiter

CSV_TEXT = "user_id,course_id,status,source_record_id\nu1,c1,completed,sr1\n"
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _isolate_limiter() -> None:
    """Reset the process-global limiter before and after every test."""
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def _client(tmp_path, name: str) -> TestClient:
    return TestClient(create_api_v1_app(LocalRepository(str(tmp_path / name))))


def test_mutating_endpoint_trips_429_after_limit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.setenv("COMPLYOS_RATE_LIMIT_PER_MINUTE", "3")
    client = _client(tmp_path, "rl-trip.db")

    body = {"csv_text": CSV_TEXT, "source_system": "csv", "profile": "workforce"}
    statuses = [
        client.post("/api/v1/imports/preview", json=body, headers=AUTH).status_code
        for _ in range(5)
    ]

    # First 3 succeed (under the limit); subsequent ones are throttled.
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429
    assert statuses[4] == 429


def test_429_body_has_structured_error_shape_and_retry_after(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.setenv("COMPLYOS_RATE_LIMIT_PER_MINUTE", "1")
    client = _client(tmp_path, "rl-shape.db")

    body = {"csv_text": CSV_TEXT, "source_system": "csv", "profile": "workforce"}
    first = client.post("/api/v1/imports/preview", json=body, headers=AUTH)
    assert first.status_code == 200

    throttled = client.post("/api/v1/imports/preview", json=body, headers=AUTH)
    assert throttled.status_code == 429

    # Structured-error shape matches every other api_v1 error (detail-wrapped ErrorBody).
    detail = throttled.json()["detail"]
    assert detail["code"] == "rate_limited"
    assert isinstance(detail["message"], str) and detail["message"]
    assert "details" in detail
    assert "request_id" in detail

    # Retry-After header is present and is a positive integer number of seconds.
    retry_after = throttled.headers.get("Retry-After")
    assert retry_after is not None
    assert int(retry_after) >= 1


def test_under_limit_requests_succeed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.setenv("COMPLYOS_RATE_LIMIT_PER_MINUTE", "5")
    client = _client(tmp_path, "rl-under.db")

    body = {"csv_text": CSV_TEXT, "source_system": "csv", "profile": "workforce"}
    statuses = [
        client.post("/api/v1/imports/preview", json=body, headers=AUTH).status_code
        for _ in range(5)
    ]

    assert statuses == [200, 200, 200, 200, 200]


def test_default_unset_limit_does_not_trip(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.delenv("COMPLYOS_RATE_LIMIT_PER_MINUTE", raising=False)
    client = _client(tmp_path, "rl-default.db")

    body = {"csv_text": CSV_TEXT, "source_system": "csv", "profile": "workforce"}
    statuses = [
        client.post("/api/v1/imports/preview", json=body, headers=AUTH).status_code
        for _ in range(40)
    ]

    # Unset means effectively unlimited: no false trips at normal-dev volumes.
    assert all(code == 200 for code in statuses)


def test_read_only_get_is_not_rate_limited(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.setenv("COMPLYOS_RATE_LIMIT_PER_MINUTE", "2")
    client = _client(tmp_path, "rl-get.db")

    statuses = [
        client.get("/api/v1/readiness", headers=AUTH).status_code for _ in range(6)
    ]

    # GETs are read-only and exempt from the mutating-endpoint limit.
    assert all(code == 200 for code in statuses)


def test_limit_is_keyed_per_path_group(monkeypatch, tmp_path) -> None:
    """One endpoint's traffic must not starve another: keys include the path group."""
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.setenv("COMPLYOS_RATE_LIMIT_PER_MINUTE", "2")
    client = _client(tmp_path, "rl-pathkey.db")

    body = {"csv_text": CSV_TEXT, "source_system": "csv", "profile": "workforce"}
    # Exhaust the imports/preview bucket.
    assert client.post("/api/v1/imports/preview", json=body, headers=AUTH).status_code == 200
    assert client.post("/api/v1/imports/preview", json=body, headers=AUTH).status_code == 200
    assert client.post("/api/v1/imports/preview", json=body, headers=AUTH).status_code == 429

    # A different mutating endpoint still has its own fresh budget.
    pref = {"channel": "slack", "event_type": "*", "enabled": True}
    other = client.put("/api/v1/notifications/preferences", json=pref, headers=AUTH)
    assert other.status_code == 200
