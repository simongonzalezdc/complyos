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


def test_api_v1_security_evidence_packet(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-security.db"))))

    response = client.get(
        "/api/v1/security/evidence",
        params={"period": "2026-Q2"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Actor-Role": "compliance_manager",
        },
    )

    assert response.status_code == 200
    assert response.json()["posture"] == "readiness_only"
    assert any(control["control_id"] == "CC7.2" for control in response.json()["controls"])


def test_api_v1_evidence_endpoint_is_tenant_scoped(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    repo = LocalRepository(str(tmp_path / "api-evidence-tenant.db"))
    repo.append_evidence_entry(
        tenant_id="tenant-a",
        query_type="audit",
        query_params={"tenant_id": "tenant-a"},
        raw_data_hash="raw-a",
        transformation_steps=["hash"],
        output_hash="tenant-a-hash",
        output_summary="tenant a evidence",
    )
    repo.append_evidence_entry(
        tenant_id="tenant-b",
        query_type="audit",
        query_params={"tenant_id": "tenant-b"},
        raw_data_hash="raw-b",
        transformation_steps=["hash"],
        output_hash="tenant-b-hash",
        output_summary="tenant b evidence",
    )
    client = TestClient(create_api_v1_app(repo))

    response = client.get(
        "/api/v1/evidence",
        headers={
            "Authorization": "Bearer test-token",
            "X-Tenant-Id": "tenant-a",
        },
    )

    assert response.status_code == 200
    output_hashes = {item["output_hash"] for item in response.json()["items"]}
    assert output_hashes == {"tenant-a-hash"}


def test_api_v1_governance_packet(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-governance.db"))))

    response = client.get(
        "/api/v1/governance/packet",
        params={"lane": "campus"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Actor-Role": "compliance_manager",
        },
    )

    assert response.status_code == 200
    assert response.json()["posture"] == "readiness_only"
    assert any(
        area["area_id"] == "ai-impact-assessment" for area in response.json()["areas"]
    )


def test_api_v1_privacy_request_and_retention_flow(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    repo = LocalRepository(str(tmp_path / "api-privacy.db"))
    client = TestClient(create_api_v1_app(repo))
    headers = {
        "Authorization": "Bearer test-token",
        "X-Actor-Role": "privacy_admin",
        "X-Tenant-Id": "tenant-a",
    }

    request = client.post(
        "/api/v1/privacy/requests",
        json={"subject_id": "u-privacy", "request_type": "access", "region": "US-CA"},
        headers=headers,
    )
    assert request.status_code == 200
    assert request.json()["tenant_id"] == "tenant-a"
    assert request.json()["status"] == "PENDING_CONTROLLER_APPROVAL"
    request_id = request.json()["request_id"]

    approved = client.post(
        f"/api/v1/privacy/requests/{request_id}/approve",
        json={"note": "controller approved"},
        headers=headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "APPROVED"

    retention = client.post(
        "/api/v1/privacy/retention-policy",
        json={
            "raw_import_days": 30,
            "evidence_days": 2555,
            "action_log_days": 2555,
            "ai_proposal_days": 180,
            "privacy_request_days": 365,
        },
        headers=headers,
    )
    assert retention.status_code == 200
    assert retention.json()["policy"]["evidence_days"] == 2555

    retention_run = client.post(
        "/api/v1/privacy/retention-policy/run",
        json={"dry_run": True},
        headers=headers,
    )
    assert retention_run.status_code == 200
    assert retention_run.json()["dry_run"] is True

    hold = client.post(
        "/api/v1/privacy/legal-holds",
        json={"subject_id": "u-privacy", "scope": "subject", "reason": "investigation"},
        headers=headers,
    )
    assert hold.status_code == 200
    assert hold.json()["status"] == "ACTIVE"
