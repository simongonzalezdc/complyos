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


def test_api_v1_audit_report_parity(monkeypatch, tmp_path) -> None:
    """The API exposes the audit/report/status/health/remediate operations too."""
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-audit.db"))))
    headers = {"Authorization": "Bearer test-token", "X-Actor-Role": "compliance_manager"}

    audit = client.get("/api/v1/audit", headers=headers)
    assert audit.status_code == 200
    assert "gaps_found" in audit.json()

    report = client.get("/api/v1/report", headers=headers)
    assert report.status_code == 200
    assert "gaps_by_severity" in report.json()

    health = client.get("/api/v1/connectors/health", headers=headers)
    assert health.status_code == 200

    # A read-only actor cannot execute remediation (mutating).
    denied = client.post(
        "/api/v1/remediate", json={}, headers={**headers, "X-Actor-Role": "read_only"}
    )
    assert denied.status_code == 403


def test_api_v1_authorization_failure_returns_403_not_400(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-403.db"))))
    headers = {
        "Authorization": "Bearer test-token",
        "X-Actor-Role": "privacy_admin",
        "X-Tenant-Id": "tenant-a",
    }
    created = client.post(
        "/api/v1/privacy/requests",
        json={"subject_id": "u1", "request_type": "deletion"},
        headers=headers,
    )
    assert created.status_code == 200
    request_id = created.json()["request_id"]

    # Deleting before controller approval is an authorization failure: the
    # service raises PermissionError, which must surface as 403, not 400.
    denied = client.post(f"/api/v1/privacy/requests/{request_id}/delete", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "privacy_delete_failed"


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


def test_api_v1_lists_connector_capability_matrix(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-connectors.db"))))
    headers = {"Authorization": "Bearer test-token", "X-Actor-Role": "compliance_manager"}

    listed = client.get("/api/v1/connectors", headers=headers)
    assert listed.status_code == 200
    matrix = listed.json()["connectors"]
    assert any(item["name"] == "csv" for item in matrix)

    filtered = client.get("/api/v1/connectors", params={"profile": "campus"}, headers=headers)
    assert filtered.status_code == 200
    assert all(item["profile"] in {"campus", "both"} for item in filtered.json()["connectors"])


def test_api_v1_connectors_list_fails_closed_for_underprivileged(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-conn-denied.db"))))

    denied = client.get(
        "/api/v1/connectors",
        headers={"Authorization": "Bearer test-token", "X-Actor-Role": "read_only"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"


def _seed_rule_repo(repo: LocalRepository) -> None:
    from datetime import date

    from complyos.models.domain import Course, EmploymentStatus, User

    repo.save_user(
        User(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 1),
            employment_status=EmploymentStatus.ACTIVE,
        )
    )
    repo.save_course(Course(id="c1", code="SEC-101", title="Security", mandatory=True))


def test_api_v1_validates_and_previews_assignment_rules(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    repo = LocalRepository(str(tmp_path / "api-rules.db"))
    _seed_rule_repo(repo)
    client = TestClient(create_api_v1_app(repo))
    headers = {"Authorization": "Bearer test-token", "X-Actor-Role": "compliance_manager"}
    body = {
        "name": "Engineering Security",
        "target_criteria": {"department": "Engineering"},
        "course_ids": ["c1"],
        "deadline_days": 30,
    }

    validated = client.post("/api/v1/rules/validate", json=body, headers=headers)
    assert validated.status_code == 200
    assert validated.json()["valid"] is True

    previewed = client.post("/api/v1/rules/preview", json=body, headers=headers)
    assert previewed.status_code == 200
    assert previewed.json()["rule_name"] == "Engineering Security"
    assert len(previewed.json()["users"]) == 1


def test_api_v1_rules_fail_closed_for_underprivileged(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-rules-denied.db"))))
    body = {
        "name": "Engineering Security",
        "target_criteria": {"department": "Engineering"},
        "course_ids": ["c1"],
    }
    # importer lacks rules:preview.
    headers = {"Authorization": "Bearer test-token", "X-Actor-Role": "importer"}

    denied_validate = client.post("/api/v1/rules/validate", json=body, headers=headers)
    assert denied_validate.status_code == 403
    assert denied_validate.json()["detail"]["code"] == "permission_denied"

    denied_preview = client.post("/api/v1/rules/preview", json=body, headers=headers)
    assert denied_preview.status_code == 403
    assert denied_preview.json()["detail"]["code"] == "permission_denied"


def test_api_v1_admin_roles_crud_and_tenant_scope(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    repo = LocalRepository(str(tmp_path / "api-admin-roles.db"))
    client = TestClient(create_api_v1_app(repo))
    # Only owner carries admin:manage.
    owner_a = {
        "Authorization": "Bearer test-token",
        "X-Actor-Role": "owner",
        "X-Tenant-Id": "tenant-a",
    }
    owner_b = {
        "Authorization": "Bearer test-token",
        "X-Actor-Role": "owner",
        "X-Tenant-Id": "tenant-b",
    }

    created = client.post(
        "/api/v1/admin/roles",
        json={"actor_id": "actor-1", "role": "reviewer"},
        headers=owner_a,
    )
    assert created.status_code == 200
    assert created.json()["role"] == "reviewer"

    # Tenant B writes its own binding for the same actor_id.
    client.post(
        "/api/v1/admin/roles",
        json={"actor_id": "actor-1", "role": "read_only"},
        headers=owner_b,
    )

    listed_a = client.get("/api/v1/admin/roles", headers=owner_a)
    assert listed_a.status_code == 200
    assert {b["role"] for b in listed_a.json()["role_bindings"]} == {"reviewer"}

    # BOLA: tenant A deleting actor-1 must not affect tenant B's binding.
    removed = client.delete("/api/v1/admin/roles/actor-1", headers=owner_a)
    assert removed.status_code == 200
    assert removed.json()["removed"] is True

    listed_b = client.get("/api/v1/admin/roles", headers=owner_b)
    assert {b["role"] for b in listed_b.json()["role_bindings"]} == {"read_only"}


def test_api_v1_admin_roles_fail_closed_for_underprivileged(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-admin-denied.db"))))
    # admin role lacks admin:manage by design.
    headers = {"Authorization": "Bearer test-token", "X-Actor-Role": "admin"}

    denied_list = client.get("/api/v1/admin/roles", headers=headers)
    assert denied_list.status_code == 403
    assert denied_list.json()["detail"]["code"] == "permission_denied"

    denied_set = client.post(
        "/api/v1/admin/roles",
        json={"actor_id": "actor-1", "role": "reviewer"},
        headers=headers,
    )
    assert denied_set.status_code == 403


def test_api_v1_admin_roles_rejects_unknown_role(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-admin-badrole.db"))))
    headers = {"Authorization": "Bearer test-token", "X-Actor-Role": "owner"}

    response = client.post(
        "/api/v1/admin/roles",
        json={"actor_id": "actor-1", "role": "not-a-role"},
        headers=headers,
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "bad_role_binding"


def test_api_v1_sync_is_permission_gated(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-sync.db"))))

    # read_only lacks audit:run; sync is mutating and must fail closed.
    denied = client.post(
        "/api/v1/sync",
        headers={"Authorization": "Bearer test-token", "X-Actor-Role": "read_only"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"

    # compliance_manager carries audit:run; sync succeeds and returns counts.
    allowed = client.post(
        "/api/v1/sync",
        headers={"Authorization": "Bearer test-token", "X-Actor-Role": "compliance_manager"},
    )
    assert allowed.status_code == 200
    assert "users" in allowed.json()["synced"]


def test_api_v1_plural_resource_aliases_reachable(monkeypatch, tmp_path) -> None:
    """Plural paths (plan §8.2) and the legacy singular aliases both work."""
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)
    client = TestClient(create_api_v1_app(LocalRepository(str(tmp_path / "api-plural.db"))))
    headers = {"Authorization": "Bearer test-token", "X-Actor-Role": "compliance_manager"}

    # /audits (canonical plural) and /audit (deprecated alias) both work.
    plural_audit = client.get("/api/v1/audits", headers=headers)
    assert plural_audit.status_code == 200
    assert "gaps_found" in plural_audit.json()
    legacy_audit = client.get("/api/v1/audit", headers=headers)
    assert legacy_audit.status_code == 200

    # /learners/{id}/status and /users/{id}/status both work.
    plural_learner = client.get("/api/v1/learners/unknown-user/status", headers=headers)
    assert plural_learner.status_code == 200
    legacy_learner = client.get("/api/v1/users/unknown-user/status", headers=headers)
    assert legacy_learner.status_code == 200

    # /remediations and /remediate both work.
    plural_remediate = client.post("/api/v1/remediations", json={}, headers=headers)
    assert plural_remediate.status_code == 200
    legacy_remediate = client.post("/api/v1/remediate", json={}, headers=headers)
    assert legacy_remediate.status_code == 200
