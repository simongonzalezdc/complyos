"""Tests for the versioned API v1."""

from __future__ import annotations

from fastapi.testclient import TestClient

from complyos.core.repository import LocalRepository
from complyos.web.api_v1 import create_api_v1_app

CSV_TEXT = "user_id,course_id,status,source_record_id\nu1,c1,completed,sr1\n"


def test_api_v1_health(tmp_path) -> None:
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api.db"))))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["service"] == "complyos-api-v1"


def test_api_v1_token_auth_and_import_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    repo = LocalRepository(str(tmp_path / "api-auth.db"))
    client = TestClient(create_api_v1_app(repo))

    denied = client.get("/api/v1/readiness")
    assert denied.status_code == 401

    headers = {"Authorization": "Bearer test-token"}
    preview = client.post(
        "/api/v1/imports/preview",
        json={"csv_text": CSV_TEXT, "source_system": "csv", "profile": "workforce"},
        headers=headers,
    )
    assert preview.status_code == 200
    batch_id = preview.json()["batch_id"]
    assert preview.json()["can_promote"] is True

    promoted = client.post(f"/api/v1/imports/{batch_id}/promote", headers=headers)
    assert promoted.status_code == 200
    assert promoted.json()["status"] == "PROMOTED"


def test_api_v1_rejects_server_side_import_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-path.db"))))

    response = client.post(
        "/api/v1/imports/preview",
        json={"path": "/etc/passwd", "source_system": "csv", "profile": "workforce"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "bad_import_request"
