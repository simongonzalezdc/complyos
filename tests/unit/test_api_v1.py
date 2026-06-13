"""Tests for the versioned API v1."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from complyos.core.repository import LocalRepository
from complyos.notification.signing import sign_payload
from complyos.web.api_v1 import create_api_v1_app

CSV_TEXT = "user_id,course_id,status,source_record_id\nu1,c1,completed,sr1\n"


def _hook_signature(secret: str, *, timestamp: str, body: bytes) -> str:
    # Exercise the production signer so inbound verification is tested end-to-end.
    return sign_payload(secret, timestamp=timestamp, body=body)


def test_api_v1_health(tmp_path) -> None:
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api.db"))))

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["service"] == "complyos-api-v1"


def test_api_v1_fails_closed_when_unconfigured(monkeypatch, tmp_path) -> None:
    """No token and no explicit insecure opt-in must reject privileged calls."""
    monkeypatch.delenv("COMPLYOS_API_TOKEN", raising=False)
    monkeypatch.delenv("COMPLYOS_ALLOW_INSECURE_LOCAL", raising=False)
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-failclosed.db"))))

    # An attacker-supplied owner role on an unauthenticated surface must NOT pass.
    response = client.get("/api/v1/readiness", headers={"X-Actor-Role": "owner"})

    assert response.status_code == 401


def test_api_v1_insecure_local_flag_allows_explicit_local_use(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("COMPLYOS_API_TOKEN", raising=False)
    monkeypatch.setenv("COMPLYOS_ALLOW_INSECURE_LOCAL", "1")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-insecure.db"))))

    response = client.get("/api/v1/readiness", headers={"X-Actor-Role": "read_only"})

    assert response.status_code == 200


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


def test_api_v1_source_intel_review_queue_and_decision(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    repo = LocalRepository(str(tmp_path / "api-source-intel.db"))
    from complyos.microlearning import MicrolearningAdapter
    from complyos.regwatch import RegWatchAdapter
    from complyos.services.context import default_local_context
    from complyos.services.source_intel import SourceIntelService
    from complyos.source_intel import (
        SourceDefinition,
        SourceIntelEngine,
        SourceSnapshot,
        SourceType,
    )
    from complyos.source_intel.monitor import SourceMonitorRun

    source = SourceDefinition(
        id="official-source",
        name="Official Source",
        url="https://example.gov/rule",
        source_type=SourceType.OFFICIAL_REGULATOR,
        authority="official",
        jurisdictions=["US"],
        topics=["safety training", "manager feedback"],
    )
    snapshot = SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title="Final rule and practice guide",
        text=(
            "A final rule says covered employers must train workers. "
            "Managers can use scenario practice, examples, and a checklist."
        ),
    )
    proposals = SourceIntelEngine(adapters=[RegWatchAdapter(), MicrolearningAdapter()]).evaluate(
        [source], [snapshot]
    )
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")
    SourceIntelService(repo).record_run(
        context,
        query="training",
        run=SourceMonitorRun(
            source_count=1,
            snapshot_count=1,
            proposal_count=len(proposals),
            proposals=proposals,
            coverage_gaps=[],
        ),
    )
    client = TestClient(create_api_v1_app(repo))
    headers = {
        "Authorization": "Bearer test-token",
        "X-Actor-Role": "compliance_manager",
        "X-Tenant-Id": "tenant-a",
    }

    listed = client.get("/api/v1/source-intel/proposals", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["proposals"]) == 2
    proposal_id = listed.json()["proposals"][0]["id"]

    decided = client.post(
        f"/api/v1/source-intel/proposals/{proposal_id}/decision",
        json={"state": "approved_for_brief"},
        headers=headers,
    )
    assert decided.status_code == 200
    assert decided.json()["approval_state"] == "approved_for_brief"

    denied = client.post(
        f"/api/v1/source-intel/proposals/{proposal_id}/decision",
        json={"state": "rejected"},
        headers={**headers, "X-Actor-Role": "read_only"},
    )
    assert denied.status_code == 403

    packet = client.get("/api/v1/source-intel/export-packet", headers=headers)
    assert packet.status_code == 200
    assert packet.json()["proposal_count"] == 2
    assert packet.json()["decided_count"] == 1


def test_api_v1_records_signed_inbound_webhook_receipt(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.setenv("COMPLYOS_INBOUND_WEBHOOK_SECRET", "inbound-secret")
    repo = LocalRepository(str(tmp_path / "api-inbound-hooks.db"))
    client = TestClient(create_api_v1_app(repo))
    body = json.dumps(
        {
            "event_type": "lms.assignment.updated",
            "object_type": "assignment",
            "object_id": "assign-1",
            "payload": {"status": "published", "api_token": "do-not-store"},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    timestamp = datetime.now(UTC).isoformat()

    response = client.post(
        "/api/v1/hooks/inbound/canvas",
        content=body,
        headers={
            "Authorization": "Bearer test-token",
            "X-Actor-Role": "compliance_manager",
            "X-Tenant-Id": "tenant-a",
            "Content-Type": "application/json",
            "X-ComplyOS-Timestamp": timestamp,
            "X-ComplyOS-Signature": _hook_signature(
                "inbound-secret",
                timestamp=timestamp,
                body=body,
            ),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "canvas"
    assert payload["event_type"] == "lms.assignment.updated"
    assert payload["tenant_id"] == "tenant-a"
    assert payload["signature_valid"] is True
    assert payload["payload"]["payload"] == {"status": "published"}


def test_api_v1_rejects_invalid_inbound_webhook_signature(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.setenv("COMPLYOS_INBOUND_WEBHOOK_SECRET", "inbound-secret")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-bad-hook.db"))))

    response = client.post(
        "/api/v1/hooks/inbound/canvas",
        json={"event_type": "lms.assignment.updated"},
        headers={
            "Authorization": "Bearer test-token",
            "X-Actor-Role": "compliance_manager",
            "X-ComplyOS-Timestamp": datetime.now(UTC).isoformat(),
            "X-ComplyOS-Signature": "sha256=wrong",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "inbound_signature_invalid"


def test_api_v1_sets_and_lists_notification_preferences(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-prefs.db"))))
    headers = {
        "Authorization": "Bearer test-token",
        "X-Actor-Role": "compliance_manager",
        "X-Tenant-Id": "tenant-a",
    }

    saved = client.put(
        "/api/v1/notifications/preferences",
        json={
            "channel": "email",
            "event_type": "privacy.request.created",
            "enabled": False,
            "reason": "send through case manager only",
        },
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["enabled"] is False

    listed = client.get("/api/v1/notifications/preferences", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["preferences"][0]["channel"] == "email"
    assert listed.json()["preferences"][0]["event_type"] == "privacy.request.created"
