"""Regression tests for the legal-hold + retention hardening (WP1).

These lock in the audit fixes for the spoliation/atomicity defects:

* subject-scoped and system-scoped legal holds must block retention deletion of
  datasets that have no per-subject linkage (fail closed), not just tenant holds;
* a system-scoped hold must block subject deletion (previously a silent no-op);
* the destructive purge and its audit-log record must commit atomically;
* every destructive delete is tenant-scoped so a wrong id list cannot cross
  tenants.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.models.domain import User
from complyos.services.context import default_local_context
from complyos.services.privacy import PrivacyProgramService

TENANT = "tenant-a"


def _configure_short_retention(service: PrivacyProgramService, context) -> None:
    service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=30,
        action_log_days=30,
        ai_proposal_days=30,
        privacy_request_days=30,
    )


def _seed_old_import_batch(repo: LocalRepository, batch_id: str, created_at: datetime) -> None:
    repo.save_import_batch(
        {
            "id": batch_id,
            "tenant_id": TENANT,
            "source_system": "csv",
            "profile": "workforce",
            "raw_file_hash": f"hash-{batch_id}",
            "status": "PROMOTED",
            "idempotency_key": f"key-{batch_id}",
            "created_by": "operator",
            "created_at": created_at,
        }
    )
    repo.save_import_rows(
        batch_id,
        [
            {
                "id": f"{batch_id}-row-1",
                "row_number": 1,
                "normalized_payload": {"employee_id": "E-sensitive"},
                "raw_payload_hash": f"row-hash-{batch_id}",
                "validation_status": "VALID",
            }
        ],
    )


def _seed_old_rejected_ai(repo: LocalRepository, proposal_id: str, created_at: datetime) -> None:
    repo.save_ai_proposal(
        {
            "id": proposal_id,
            "tenant_id": TENANT,
            "proposal_type": "policy_recommendation",
            "input_hash": f"input-{proposal_id}",
            "output_hash": f"output-{proposal_id}",
            "status": "REJECTED",
            "created_by": "agent",
            "created_at": created_at,
            "output": {"recommendation": "disposable"},
        }
    )


def _seed_closed_privacy_request(
    repo: LocalRepository, request_id: str, subject_id: str, created_at: datetime
) -> None:
    repo.save_privacy_request(
        {
            "id": request_id,
            "tenant_id": TENANT,
            "subject_id": subject_id,
            "request_type": "access",
            "status": "COMPLETED",
            "opened_by": "operator",
            "created_at": created_at,
            "result_summary": {"controller_approval": {"status": "approved"}},
        }
    )


def test_subject_hold_fails_closed_on_unlinked_datasets_but_is_granular_for_requests(
    tmp_path,
) -> None:
    """A subject-scoped hold must protect every dataset, not just tenant-wide holds.

    Import payloads, AI proposals, evidence, and action logs have no per-subject
    linkage, so an active subject hold makes them fail closed (skip the whole
    tenant). Privacy requests DO carry subject_id, so only the held subject's
    request is preserved while another subject's request is still purged.
    """
    repo = LocalRepository(str(tmp_path / "subject-hold.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id=TENANT, role="privacy_admin")
    old_at = datetime.now(UTC) - timedelta(days=60)

    _configure_short_retention(service, context)
    _seed_old_import_batch(repo, "held-import", old_at)
    _seed_old_rejected_ai(repo, "held-ai", old_at)
    repo.append_evidence_entry(
        tenant_id=TENANT,
        query_type="old.evidence",
        query_params={"tenant_id": TENANT},
        raw_data_hash="raw-old",
        transformation_steps=["hash"],
        output_hash="evidence-old",
        output_summary="old evidence",
        timestamp=old_at,
    )
    _seed_closed_privacy_request(repo, "req-held", "u-held", old_at)
    _seed_closed_privacy_request(repo, "req-other", "u-other", old_at)

    service.create_legal_hold(
        context, subject_id="u-held", scope="subject", reason="investigation"
    )

    applied = service.run_retention_cleanup(context, dry_run=False)

    # Unlinked datasets fail closed while ANY hold is active.
    assert applied.eligible_counts["raw_import_rows"] == 0
    assert applied.eligible_counts["ai_proposals"] == 0
    assert applied.eligible_counts["evidence_ledger"] == 0
    assert applied.deleted_counts["raw_import_rows"] == 0
    assert applied.deleted_counts["ai_proposals"] == 0
    assert applied.deleted_counts["evidence_ledger"] == 0
    assert repo.list_import_rows("held-import") != []
    assert repo.get_ai_proposal("held-ai") is not None
    assert repo.list_evidence_ledger(tenant_id=TENANT) != []

    # Privacy requests are subject-granular: held subject preserved, other purged.
    assert applied.deleted_counts["privacy_requests"] == 1
    assert repo.get_privacy_request("req-held") is not None
    assert repo.get_privacy_request("req-other") is None


def test_system_scope_hold_blocks_subject_deletion(tmp_path) -> None:
    """A scope='system' hold must block subject deletion (previously ignored)."""
    repo = LocalRepository(str(tmp_path / "system-hold-delete.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id=TENANT, role="privacy_admin")

    repo.save_user(
        User(
            id="u-sys",
            employee_id="E-sys",
            email="sys@example.com",
            first_name="Sys",
            last_name="Subject",
            department="Legal",
            region="US",
            hire_date=date(2024, 1, 1),
            custom_attributes={"tenant_id": TENANT},
        )
    )
    request = service.create_request(context, subject_id="u-sys", request_type="deletion")
    service.approve_request(context, request.request_id, approval_note="approved")
    service.create_legal_hold(
        context, subject_id=None, scope="system", reason="organization-wide hold"
    )

    blocked = service.delete_subject(context, request.request_id)

    assert blocked.status == "BLOCKED_LEGAL_HOLD"
    assert repo.get_user("u-sys") is not None


def test_system_scope_hold_blocks_all_retention_datasets(tmp_path) -> None:
    """A scope='system' hold must block retention cleanup of every dataset."""
    repo = LocalRepository(str(tmp_path / "system-hold-retention.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id=TENANT, role="privacy_admin")
    old_at = datetime.now(UTC) - timedelta(days=60)

    _configure_short_retention(service, context)
    _seed_closed_privacy_request(repo, "req-old", "u-old", old_at)
    _seed_old_rejected_ai(repo, "ai-old", old_at)
    service.create_legal_hold(
        context, subject_id=None, scope="system", reason="system litigation hold"
    )

    applied = service.run_retention_cleanup(context, dry_run=False)

    assert applied.deleted_counts["privacy_requests"] == 0
    assert applied.deleted_counts["ai_proposals"] == 0
    assert repo.get_privacy_request("req-old") is not None
    assert repo.get_ai_proposal("ai-old") is not None


def test_retention_purge_is_atomic_with_its_audit_log(tmp_path, monkeypatch) -> None:
    """If writing the audit record fails, every delete in the purge rolls back."""
    repo = LocalRepository(str(tmp_path / "atomic.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id=TENANT, role="privacy_admin")
    old_at = datetime.now(UTC) - timedelta(days=60)

    _configure_short_retention(service, context)
    _seed_closed_privacy_request(repo, "req-old", "u-old", old_at)

    # Force the in-transaction audit-log write to fail AFTER the deletes are
    # staged. utc_now() is only evaluated when building the audit-log row inside
    # the purge transaction (the eligibility reads use the passed cutoff), so
    # raising here exercises exactly the deletes-staged-then-log-fails path.
    import complyos.core.privacy_repo as privacy_repo_module

    def _boom() -> datetime:
        raise RuntimeError("simulated audit-log write failure")

    monkeypatch.setattr(privacy_repo_module, "utc_now", _boom)

    with pytest.raises(RuntimeError, match="simulated audit-log write failure"):
        service.run_retention_cleanup(context, dry_run=False)

    # The eligible record must still exist: the delete rolled back with the log.
    assert repo.get_privacy_request("req-old") is not None


def test_purge_delete_is_tenant_scoped(tmp_path) -> None:
    """A purge invoked for the wrong tenant must not delete another tenant's rows."""
    repo = LocalRepository(str(tmp_path / "tenant-guard.db"))
    old_at = datetime.now(UTC) - timedelta(days=60)
    repo.append_evidence_entry(
        tenant_id=TENANT,
        query_type="old.evidence",
        query_params={"tenant_id": TENANT},
        raw_data_hash="raw-old",
        transformation_steps=["hash"],
        output_hash="evidence-old",
        output_summary="old evidence",
        timestamp=old_at,
    )
    eligible = repo.list_retention_eligible_evidence_ids(
        tenant_id=TENANT, cutoff=datetime.now(UTC) - timedelta(days=30)
    )
    assert eligible  # the row is eligible for tenant-a

    # Invoke the purge as a DIFFERENT tenant with tenant-a's ids.
    deleted = repo.purge_retention_eligible(
        tenant_id="tenant-b",
        privacy_request_ids=[],
        import_batch_ids=[],
        ai_proposal_ids=[],
        evidence_ids=eligible,
        action_log_ids=[],
        actor_id="attacker",
        surface="test",
        request_id=None,
        log_metadata={"dry_run": False},
    )

    assert deleted["evidence_ledger"] == 0
    assert repo.list_evidence_ledger(tenant_id=TENANT) != []
