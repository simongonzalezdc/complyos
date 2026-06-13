"""Runtime privacy program workflow tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.models.domain import LearningRecord, LearningRecordStatus, PrivacyRequest, User
from complyos.services.context import default_local_context
from complyos.services.notifications import NotificationOutboxService
from complyos.services.privacy import PrivacyProgramService


def _save_subject(repo: LocalRepository, *, tenant_id: str = "local-default") -> None:
    repo.save_user(
        User(
            id="u-privacy",
            employee_id="E-privacy",
            email="privacy@example.com",
            first_name="Privacy",
            last_name="Subject",
            department="Legal",
            region="US",
            hire_date=date(2024, 1, 1),
            custom_attributes={"tenant_id": tenant_id},
        )
    )
    repo.save_learning_record(
        LearningRecord(
            id="lr-privacy",
            user_id="u-privacy",
            course_id="security-101",
            source_system="csv",
            status=LearningRecordStatus.COMPLETED,
            raw_source_hash="hash-privacy",
        )
    )


def test_privacy_request_export_delete_and_legal_hold_flow(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "privacy.db"))
    _save_subject(repo)
    service = PrivacyProgramService(repo)
    context = default_local_context(surface="cli", role="privacy_admin")

    request = service.create_request(
        context,
        subject_id="u-privacy",
        request_type="deletion",
        region="US-CA",
        notes="employee deletion request",
    )
    assert request.status == "PENDING_CONTROLLER_APPROVAL"

    with pytest.raises(PermissionError, match="controller approval"):
        service.export_subject(context, request.request_id)

    approved = service.approve_request(
        context,
        request.request_id,
        approval_note="controller approved identity and lawful-basis check",
    )
    assert approved.status == "APPROVED"

    export = service.export_subject(context, request.request_id)

    assert export.subject["email"] == "privacy@example.com"
    assert export.record_counts["learning_records"] == 1

    hold = service.create_legal_hold(
        context,
        subject_id="u-privacy",
        scope="subject",
        reason="pending investigation",
    )
    blocked = service.delete_subject(context, request.request_id)

    assert blocked.status == "BLOCKED_LEGAL_HOLD"
    assert blocked.deleted_records == {}
    assert repo.get_user("u-privacy") is not None

    released = service.release_legal_hold(context, hold.hold_id)
    completed = service.delete_subject(context, request.request_id)

    assert released.status == "RELEASED"
    assert completed.status == "COMPLETED"
    assert completed.deleted_records["users"] == 1
    assert completed.deleted_records["learning_records"] == 1
    assert repo.get_user("u-privacy") is None


def test_privacy_request_controller_approval_gate() -> None:
    """The approval gate is a typed predicate on the model, not a dict lookup."""
    base = {
        "id": "r1",
        "tenant_id": "t",
        "subject_id": "s",
        "request_type": "deletion",
        "status": "PENDING_CONTROLLER_APPROVAL",
        "opened_by": "op",
        "created_at": datetime.now(UTC),
    }
    assert PrivacyRequest(**base).is_controller_approved() is False
    approved = PrivacyRequest(
        **base, result_summary={"controller_approval": {"status": "approved"}}
    )
    assert approved.is_controller_approved() is True


def test_invalid_request_type_and_hold_scope_are_rejected(tmp_path) -> None:
    """Validation is enum-driven (PrivacyRequestType / LegalHoldScope)."""
    repo = LocalRepository(str(tmp_path / "invalid.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(role="privacy_admin")

    with pytest.raises(ValueError, match="unsupported privacy request type"):
        service.create_request(context, subject_id="u1", request_type="nonsense")

    with pytest.raises(ValueError, match="unsupported legal hold scope"):
        service.create_legal_hold(context, subject_id="u1", scope="nonsense", reason="x")


def test_privacy_request_is_tenant_scoped(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "tenant.db"))
    _save_subject(repo, tenant_id="tenant-a")
    service = PrivacyProgramService(repo)
    tenant_a = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    tenant_b = default_local_context(tenant_id="tenant-b", role="privacy_admin")

    request = service.create_request(tenant_a, subject_id="u-privacy", request_type="access")

    with pytest.raises(PermissionError):
        service.export_subject(tenant_b, request.request_id)


def test_privacy_workflows_enqueue_notification_events(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "privacy-notifications.db"))
    _save_subject(repo)
    service = PrivacyProgramService(repo)
    context = default_local_context(surface="cli", role="privacy_admin")

    request = service.create_request(
        context,
        subject_id="u-privacy",
        request_type="deletion",
        region="US-CA",
    )
    service.approve_request(context, request.request_id, approval_note="approved")
    hold = service.create_legal_hold(
        context,
        subject_id="u-privacy",
        scope="subject",
        reason="investigation",
    )
    service.delete_subject(context, request.request_id)
    service.release_legal_hold(context, hold.hold_id)
    service.delete_subject(context, request.request_id)
    service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=2555,
        action_log_days=2555,
        ai_proposal_days=180,
        privacy_request_days=365,
    )
    service.run_retention_cleanup(context, dry_run=True)

    deliveries = NotificationOutboxService(repo).list_pending_deliveries(context, limit=100)
    event_types = {delivery["event"]["event_type"] for delivery in deliveries}
    assert {
        "privacy.request.created",
        "privacy.request.approved",
        "privacy.legal_hold.created",
        "privacy.delete.blocked_by_legal_hold",
        "privacy.legal_hold.released",
        "privacy.delete.completed",
        "privacy.retention.run",
    } <= event_types


def test_retention_policy_is_tenant_scoped_and_records_audit_log(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "retention.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")

    result = service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=2555,
        action_log_days=2555,
        ai_proposal_days=180,
    )

    assert result.tenant_id == "tenant-a"
    assert result.policy["raw_import_days"] == 30
    assert result.policy["evidence_days"] == 2555
    assert repo.get_retention_policy("tenant-a")["ai_proposal_days"] == 180
    assert repo.list_action_logs(tenant_id="tenant-a")[0]["action"] == "privacy.retention.configure"


def test_retention_cleanup_dry_run_then_apply_removes_closed_privacy_cases(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "retention-run.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    now = datetime.now(UTC)

    service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=2555,
        action_log_days=2555,
        ai_proposal_days=180,
        privacy_request_days=30,
    )
    repo.save_privacy_request(
        PrivacyRequest(
            id="old-closed",
            tenant_id="tenant-a",
            subject_id="u-old",
            request_type="access",
            status="COMPLETED",
            opened_by="operator",
            created_at=now - timedelta(days=60),
            result_summary={"controller_approval": {"status": "approved"}},
        )
    )
    repo.save_privacy_request(
        PrivacyRequest(
            id="recent-closed",
            tenant_id="tenant-a",
            subject_id="u-recent",
            request_type="access",
            status="COMPLETED",
            opened_by="operator",
            created_at=now - timedelta(days=5),
            result_summary={"controller_approval": {"status": "approved"}},
        )
    )

    dry_run = service.run_retention_cleanup(context, dry_run=True)

    assert dry_run.dry_run is True
    assert dry_run.eligible_counts["privacy_requests"] == 1
    assert dry_run.deleted_counts["privacy_requests"] == 0
    assert repo.get_privacy_request("old-closed") is not None

    applied = service.run_retention_cleanup(context, dry_run=False)

    assert applied.dry_run is False
    assert applied.eligible_counts["privacy_requests"] == 1
    assert applied.deleted_counts["privacy_requests"] == 1
    assert repo.get_privacy_request("old-closed") is None
    assert repo.get_privacy_request("recent-closed") is not None
    assert any(
        item["action"] == "privacy.retention.run"
        for item in repo.list_action_logs(tenant_id="tenant-a")
    )


def test_retention_cleanup_purges_old_raw_import_rows_and_rejected_ai_proposals(
    tmp_path,
) -> None:
    repo = LocalRepository(str(tmp_path / "retention-import-ai.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    now = datetime.now(UTC)

    service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=30,
        action_log_days=30,
        ai_proposal_days=30,
        privacy_request_days=365,
    )
    for batch_id, created_at in (
        ("old-import", now - timedelta(days=60)),
        ("recent-import", now - timedelta(days=5)),
    ):
        repo.save_import_batch(
            {
                "id": batch_id,
                "tenant_id": "tenant-a",
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
                    "normalized_payload": {
                        "employee_id": "E-sensitive",
                        "email": f"{batch_id}@example.com",
                    },
                    "raw_payload_hash": f"row-hash-{batch_id}",
                    "validation_status": "VALID",
                }
            ],
        )
        repo.save_import_decision(
            {
                "id": f"{batch_id}-decision",
                "batch_id": batch_id,
                "row_id": f"{batch_id}-row-1",
                "decision_type": "accept",
                "decision_payload": {"email": f"{batch_id}@example.com"},
                "decided_by": "operator",
                "decided_at": created_at,
            }
        )

    for proposal_id, status, created_at in (
        ("old-rejected-ai", "REJECTED", now - timedelta(days=60)),
        ("recent-rejected-ai", "REJECTED", now - timedelta(days=5)),
        ("old-approved-ai", "APPROVED", now - timedelta(days=60)),
    ):
        repo.save_ai_proposal(
            {
                "id": proposal_id,
                "tenant_id": "tenant-a",
                "proposal_type": "policy_recommendation",
                "input_hash": f"input-{proposal_id}",
                "output_hash": f"output-{proposal_id}",
                "status": status,
                "created_by": "agent",
                "created_at": created_at,
                "output": {"recommendation": f"sensitive {proposal_id}"},
                "provenance": {
                    "model_provider": "local",
                    "model_name": "test-model",
                    "prompt_hash": f"prompt-{proposal_id}",
                    "redaction_policy": "hash-only",
                },
            }
        )

    dry_run = service.run_retention_cleanup(context, dry_run=True)

    assert dry_run.eligible_counts["raw_import_rows"] == 1
    assert dry_run.eligible_counts["import_decisions"] == 1
    assert dry_run.eligible_counts["ai_proposals"] == 1
    assert dry_run.deleted_counts["raw_import_rows"] == 0
    assert repo.list_import_rows("old-import") != []
    assert repo.get_ai_proposal("old-rejected-ai") is not None

    applied = service.run_retention_cleanup(context, dry_run=False)

    assert applied.eligible_counts["raw_import_rows"] == 1
    assert applied.deleted_counts["raw_import_rows"] == 1
    assert applied.deleted_counts["import_decisions"] == 1
    assert applied.deleted_counts["ai_proposals"] == 1
    assert repo.get_import_batch("old-import") is not None
    assert repo.list_import_rows("old-import") == []
    assert repo.list_import_decisions("old-import") == []
    assert repo.list_import_rows("recent-import") != []
    assert repo.list_import_decisions("recent-import") != []
    assert repo.get_ai_proposal("old-rejected-ai") is None
    assert repo.get_ai_proposal("recent-rejected-ai") is not None
    assert repo.get_ai_proposal("old-approved-ai") is not None


def test_retention_cleanup_respects_tenant_legal_hold_for_import_and_ai_payloads(
    tmp_path,
) -> None:
    repo = LocalRepository(str(tmp_path / "retention-hold.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    old_at = datetime.now(UTC) - timedelta(days=60)

    service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=30,
        action_log_days=30,
        ai_proposal_days=30,
        privacy_request_days=365,
    )
    repo.save_import_batch(
        {
            "id": "held-import",
            "tenant_id": "tenant-a",
            "source_system": "csv",
            "profile": "workforce",
            "raw_file_hash": "hash-held-import",
            "status": "PROMOTED",
            "idempotency_key": "key-held-import",
            "created_by": "operator",
            "created_at": old_at,
        }
    )
    repo.save_import_rows(
        "held-import",
        [
            {
                "id": "held-import-row-1",
                "row_number": 1,
                "normalized_payload": {"employee_id": "E-held"},
                "raw_payload_hash": "row-hash-held-import",
                "validation_status": "VALID",
            }
        ],
    )
    repo.save_ai_proposal(
        {
            "id": "held-ai",
            "tenant_id": "tenant-a",
            "proposal_type": "policy_recommendation",
            "input_hash": "input-held-ai",
            "output_hash": "output-held-ai",
            "status": "REJECTED",
            "created_by": "agent",
            "created_at": old_at,
            "output": {"recommendation": "hold this"},
        }
    )
    repo.append_evidence_entry(
        tenant_id="tenant-a",
        query_type="held.evidence",
        query_params={"tenant_id": "tenant-a"},
        raw_data_hash="raw-held",
        transformation_steps=["hash"],
        output_hash="evidence-held",
        output_summary="held evidence",
        timestamp=old_at,
    )
    repo.save_action_log(
        tenant_id="tenant-a",
        actor_id="operator",
        surface="test",
        action="held.action",
        object_type="evidence",
        object_id="held",
        result="success",
        request_id=None,
        metadata={},
        created_at=old_at,
    )
    service.create_legal_hold(
        context,
        subject_id=None,
        scope="tenant",
        reason="pending litigation hold",
    )

    applied = service.run_retention_cleanup(context, dry_run=False)

    assert applied.eligible_counts["raw_import_rows"] == 0
    assert applied.eligible_counts["ai_proposals"] == 0
    assert applied.eligible_counts["evidence_ledger"] == 0
    assert applied.eligible_counts["action_logs"] == 0
    assert applied.deleted_counts["raw_import_rows"] == 0
    assert applied.deleted_counts["ai_proposals"] == 0
    assert applied.deleted_counts["evidence_ledger"] == 0
    assert applied.deleted_counts["action_logs"] == 0
    assert repo.list_import_rows("held-import") != []
    assert repo.get_ai_proposal("held-ai") is not None
    assert repo.list_evidence_ledger(tenant_id="tenant-a") != []
    assert any(
        item["action"] == "held.action"
        for item in repo.list_action_logs(tenant_id="tenant-a")
    )


def test_retention_cleanup_purges_old_evidence_and_action_logs_by_tenant(
    tmp_path,
) -> None:
    repo = LocalRepository(str(tmp_path / "retention-evidence-logs.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    old_at = datetime.now(UTC) - timedelta(days=60)
    recent_at = datetime.now(UTC) - timedelta(days=5)

    service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=30,
        action_log_days=30,
        ai_proposal_days=30,
        privacy_request_days=365,
    )
    repo.append_evidence_entry(
        tenant_id="tenant-a",
        query_type="old.evidence",
        query_params={"tenant_id": "tenant-a"},
        raw_data_hash="raw-old-a",
        transformation_steps=["hash"],
        output_hash="evidence-old-a",
        output_summary="old tenant a evidence",
        timestamp=old_at,
    )
    repo.append_evidence_entry(
        tenant_id="tenant-a",
        query_type="recent.evidence",
        query_params={"tenant_id": "tenant-a"},
        raw_data_hash="raw-recent-a",
        transformation_steps=["hash"],
        output_hash="evidence-recent-a",
        output_summary="recent tenant a evidence",
        timestamp=recent_at,
    )
    repo.append_evidence_entry(
        tenant_id="tenant-b",
        query_type="old.evidence",
        query_params={"tenant_id": "tenant-b"},
        raw_data_hash="raw-old-b",
        transformation_steps=["hash"],
        output_hash="evidence-old-b",
        output_summary="old tenant b evidence",
        timestamp=old_at,
    )
    repo.save_action_log(
        tenant_id="tenant-a",
        actor_id="operator",
        surface="test",
        action="old.action",
        object_type="evidence",
        object_id="old-a",
        result="success",
        request_id=None,
        metadata={},
        created_at=old_at,
    )
    repo.save_action_log(
        tenant_id="tenant-a",
        actor_id="operator",
        surface="test",
        action="recent.action",
        object_type="evidence",
        object_id="recent-a",
        result="success",
        request_id=None,
        metadata={},
        created_at=recent_at,
    )
    repo.save_action_log(
        tenant_id="tenant-b",
        actor_id="operator",
        surface="test",
        action="old.action",
        object_type="evidence",
        object_id="old-b",
        result="success",
        request_id=None,
        metadata={},
        created_at=old_at,
    )

    dry_run = service.run_retention_cleanup(context, dry_run=True)

    assert dry_run.eligible_counts["evidence_ledger"] == 1
    assert dry_run.eligible_counts["action_logs"] == 1
    assert dry_run.deleted_counts["evidence_ledger"] == 0
    assert dry_run.deleted_counts["action_logs"] == 0

    applied = service.run_retention_cleanup(context, dry_run=False)

    tenant_a_evidence_hashes = {
        item["output_hash"] for item in repo.list_evidence_ledger(tenant_id="tenant-a")
    }
    tenant_b_evidence_hashes = {
        item["output_hash"] for item in repo.list_evidence_ledger(tenant_id="tenant-b")
    }
    tenant_a_actions = {item["action"] for item in repo.list_action_logs(tenant_id="tenant-a")}
    tenant_b_actions = {item["action"] for item in repo.list_action_logs(tenant_id="tenant-b")}

    assert applied.deleted_counts["evidence_ledger"] == 1
    assert applied.deleted_counts["action_logs"] == 1
    assert "evidence-old-a" not in tenant_a_evidence_hashes
    assert "evidence-recent-a" in tenant_a_evidence_hashes
    assert "evidence-old-b" in tenant_b_evidence_hashes
    assert "old.action" not in tenant_a_actions
    assert "recent.action" in tenant_a_actions
    assert "old.action" in tenant_b_actions
