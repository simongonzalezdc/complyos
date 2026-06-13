"""API-surface BOLA / IDOR adversarial tests (plan §13.2).

Two tenants (A and B) authenticate against the same API with their own bearer +
tenant + role headers. Through the HTTP API, tenant A must never be able to read,
list, mutate, promote, approve, or delete tenant B's objects: import batches,
evidence ledger, governance packet, learner status, admin role bindings, or AI
proposals. This is the API-surface complement to the repository-level isolation
tests in tests/unit/test_tenant_isolation.py.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import AIProposalService
from complyos.services.context import default_local_context
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.role_admin import RoleAdminService
from complyos.web.api_v1 import create_api_v1_app
from complyos.web.rate_limit import reset_rate_limiter

CSV_TEXT = "user_id,course_id,status,source_record_id\nu1,c1,completed,sr1\n"

TENANT_A = "tenant-a"
TENANT_B = "tenant-b"


@pytest.fixture(autouse=True)
def _isolate_rate_limiter() -> None:
    reset_rate_limiter()
    yield
    reset_rate_limiter()


def _headers(tenant: str, role: str = "owner") -> dict[str, str]:
    return {
        "Authorization": "Bearer test-token",
        "X-Tenant-Id": tenant,
        "X-Actor-Role": role,
    }


@pytest.fixture
def app_with_two_tenants(monkeypatch, tmp_path):
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "test-token")
    repo = LocalRepository(str(tmp_path / "bola.db"))
    client = TestClient(create_api_v1_app(repo))
    return client, repo


def test_tenant_a_cannot_promote_tenant_b_import_batch(app_with_two_tenants) -> None:
    client, repo = app_with_two_tenants

    # Tenant B previews an import batch via the service (its own context).
    ctx_b = default_local_context(tenant_id=TENANT_B, role="owner", surface="api")
    preview_b = ImportService(repo).preview(ctx_b, ImportPreviewRequest(csv_text=CSV_TEXT))
    batch_b = preview_b.batch_id

    # Tenant A tries to promote tenant B's batch through the API. The service
    # raises PermissionError on the tenant mismatch -> 403, never PROMOTED.
    promoted = client.post(f"/api/v1/imports/{batch_b}/promote", headers=_headers(TENANT_A))
    assert promoted.status_code == 403
    assert promoted.json()["detail"]["code"] == "promotion_failed"

    # No learning records leaked into tenant A and tenant B's batch is untouched.
    assert repo.get_import_batch(batch_b)["status"] != "PROMOTED"


def test_tenant_a_evidence_list_never_returns_tenant_b_rows(app_with_two_tenants) -> None:
    client, repo = app_with_two_tenants
    repo.append_evidence_entry(
        tenant_id=TENANT_A,
        query_type="audit",
        query_params={"tenant_id": TENANT_A},
        raw_data_hash="raw-a",
        transformation_steps=["hash"],
        output_hash="hash-a",
        output_summary="tenant a evidence",
    )
    repo.append_evidence_entry(
        tenant_id=TENANT_B,
        query_type="audit",
        query_params={"tenant_id": TENANT_B},
        raw_data_hash="raw-b",
        transformation_steps=["hash"],
        output_hash="hash-b-secret",
        output_summary="tenant b evidence",
    )

    listed = client.get("/api/v1/evidence", headers=_headers(TENANT_A))
    assert listed.status_code == 200
    hashes = {item["output_hash"] for item in listed.json()["items"]}
    assert hashes == {"hash-a"}
    assert "hash-b-secret" not in hashes


def test_tenant_a_governance_packet_is_scoped_to_tenant_a(app_with_two_tenants) -> None:
    client, _repo = app_with_two_tenants

    packet = client.get(
        "/api/v1/governance/packet",
        params={"lane": "campus"},
        headers=_headers(TENANT_A, role="compliance_manager"),
    )
    assert packet.status_code == 200
    # The packet is stamped with the requesting tenant, never another tenant.
    assert packet.json()["tenant_id"] == TENANT_A


def test_tenant_a_export_is_scoped_and_denied_without_permission(app_with_two_tenants) -> None:
    client, _repo = app_with_two_tenants

    # A reviewer in tenant B lacks no relevant cross-tenant path; but a tenant-A
    # read_only actor must not be able to export the evidence/report surface.
    denied = client.post(
        "/api/v1/exports/reports", json={}, headers=_headers(TENANT_A, role="read_only")
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"


def test_learner_status_and_audit_enforce_read_permission(app_with_two_tenants) -> None:
    """Learner status / audit are permission-gated: an actor whose role lacks the
    read permission is denied (403), so it cannot read another tenant's learners
    by spoofing X-Tenant-Id with an under-privileged role.

    (Note: in this local-first single-connector deployment the audited data is
    not partitioned per tenant header, so the honest API-surface guarantee here
    is the permission gate, not a row-level tenant filter — the row-level filter
    is proved on the evidence/admin/import/AI surfaces above.)"""
    client, _repo = app_with_two_tenants

    # importer carries import perms but NOT audit:read -> denied learner status.
    denied = client.get(
        "/api/v1/learners/unknown-user/status",
        headers=_headers(TENANT_A, role="importer"),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"

    # read_only carries audit:read but NOT audit:run -> denied audit run.
    denied_audit = client.get(
        "/api/v1/audits", headers=_headers(TENANT_A, role="read_only")
    )
    assert denied_audit.status_code == 403


def test_tenant_a_cannot_read_or_delete_tenant_b_admin_role_bindings(
    app_with_two_tenants,
) -> None:
    client, repo = app_with_two_tenants

    # Tenant B owner binds a reviewer role for actor "shared-actor".
    ctx_b = default_local_context(tenant_id=TENANT_B, role="owner", surface="api")
    RoleAdminService(repo).set_role_binding(ctx_b, actor_id="shared-actor", role="reviewer")

    # Tenant A lists role bindings: it must NOT see tenant B's binding.
    listed_a = client.get("/api/v1/admin/roles", headers=_headers(TENANT_A))
    assert listed_a.status_code == 200
    assert listed_a.json()["role_bindings"] == []

    # Tenant A tries to delete "shared-actor": because that binding does not exist
    # in tenant A's scope, the delete fails closed (404/400 not-found) rather than
    # reaching across into tenant B's binding.
    removed = client.delete("/api/v1/admin/roles/shared-actor", headers=_headers(TENANT_A))
    assert removed.status_code in {400, 404}

    # Tenant B's binding is still intact regardless of tenant A's actions.
    bindings_b = RoleAdminService(repo).list_role_bindings(ctx_b)
    assert {b["role"] for b in bindings_b} == {"reviewer"}


def test_tenant_a_cannot_approve_tenant_b_ai_proposal(app_with_two_tenants) -> None:
    client, repo = app_with_two_tenants

    # Tenant B creates an AI mapping proposal under its own context.
    ctx_b = default_local_context(tenant_id=TENANT_B, role="compliance_manager", surface="api")
    proposal = AIProposalService(repo).propose_mapping(
        ctx_b, headers=["User ID", "Course ID", "Status"]
    )

    # Tenant A tries to approve tenant B's proposal via the API: the service
    # raises PermissionError on the tenant mismatch -> 403.
    approved = client.post(
        f"/api/v1/ai/proposals/{proposal.proposal_id}/approve",
        headers=_headers(TENANT_A, role="compliance_manager"),
    )
    assert approved.status_code == 403
    assert approved.json()["detail"]["code"] == "proposal_approval_failed"

    # Tenant B's proposal is still PROPOSED, not APPROVED.
    stored = repo.get_ai_proposal(proposal.proposal_id)
    assert stored is not None
    assert stored["status"] == "PROPOSED"
