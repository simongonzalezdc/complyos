"""Privacy program workflows for DSR, retention, and legal holds.

These services implement operational workflows only. They do not provide legal
advice and do not claim GDPR/CCPA/FERPA compliance.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_LEGAL_HOLD_MANAGE,
    PERM_PRIVACY_APPROVE,
    PERM_PRIVACY_DELETE,
    PERM_PRIVACY_EXPORT,
    PERM_PRIVACY_REQUEST,
    PERM_PRIVACY_RETENTION_MANAGE,
    ActorContext,
    require_permission,
)
from complyos.services.notifications import NotificationOutboxService

PRIVACY_NOTIFICATION_CHANNELS = ["email", "slack", "teams"]


class PrivacyRequestResult(BaseModel):
    request_id: str
    tenant_id: str
    subject_id: str
    request_type: str
    status: str
    region: str | None = None
    created_at: datetime
    actor_context: dict[str, str] = Field(default_factory=dict)


class DataSubjectExportResult(BaseModel):
    request_id: str
    tenant_id: str
    subject_id: str
    status: str
    subject: dict[str, object]
    learning_records: list[dict[str, object]]
    enrollments: list[dict[str, object]]
    record_counts: dict[str, int]
    generated_at: datetime
    actor_context: dict[str, str] = Field(default_factory=dict)


class DeletionResult(BaseModel):
    request_id: str
    tenant_id: str
    subject_id: str
    status: str
    deleted_records: dict[str, int] = Field(default_factory=dict)
    blocked_by_holds: list[str] = Field(default_factory=list)
    completed_at: datetime | None = None
    actor_context: dict[str, str] = Field(default_factory=dict)


class LegalHoldResult(BaseModel):
    hold_id: str
    tenant_id: str
    subject_id: str | None
    scope: str
    reason: str
    status: str
    created_at: datetime | None = None
    released_at: datetime | None = None
    actor_context: dict[str, str] = Field(default_factory=dict)


class RetentionPolicyResult(BaseModel):
    tenant_id: str
    policy: dict[str, int]
    updated_at: datetime
    actor_context: dict[str, str] = Field(default_factory=dict)


class RetentionCleanupResult(BaseModel):
    tenant_id: str
    dry_run: bool
    policy: dict[str, int]
    cutoff_by_dataset: dict[str, datetime]
    eligible_counts: dict[str, int] = Field(default_factory=dict)
    deleted_counts: dict[str, int] = Field(default_factory=dict)
    generated_at: datetime
    actor_context: dict[str, str] = Field(default_factory=dict)


class PrivacyProgramService:
    """Operational privacy workflows over repository-backed records."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def create_request(
        self,
        context: ActorContext,
        *,
        subject_id: str,
        request_type: str,
        region: str | None = None,
        notes: str | None = None,
    ) -> PrivacyRequestResult:
        require_permission(context, PERM_PRIVACY_REQUEST)
        allowed = {"access", "export", "correction", "deletion", "restriction", "objection"}
        if request_type not in allowed:
            raise ValueError(f"unsupported privacy request type: {request_type}")
        created_at = datetime.now(UTC)
        request_id = str(uuid4())
        self.repository.save_privacy_request(
            {
                "id": request_id,
                "tenant_id": context.tenant_id,
                "subject_id": subject_id,
                "request_type": request_type,
                "status": "PENDING_CONTROLLER_APPROVAL",
                "region": region,
                "opened_by": context.actor_id,
                "created_at": created_at,
                "metadata": {"notes": notes} if notes else {},
            }
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="privacy.request.create",
            object_type="privacy_request",
            object_id=request_id,
            result="success",
            request_id=context.request_id,
            metadata={"request_type": request_type, "region": region},
        )
        self._enqueue_privacy_event(
            context,
            event_type="privacy.request.created",
            object_type="privacy_request",
            object_id=request_id,
            payload={
                "request_type": request_type,
                "region": region,
                "status": "PENDING_CONTROLLER_APPROVAL",
                "email_subject": "ComplyOS privacy request needs controller approval",
                "summary": (
                    f"Privacy {request_type} request {request_id} was opened for "
                    f"subject {subject_id}."
                ),
            },
        )
        return PrivacyRequestResult(
            request_id=request_id,
            tenant_id=context.tenant_id,
            subject_id=subject_id,
            request_type=request_type,
            status="PENDING_CONTROLLER_APPROVAL",
            region=region,
            created_at=created_at,
            actor_context=context.public_dict(),
        )

    def approve_request(
        self,
        context: ActorContext,
        request_id: str,
        *,
        approval_note: str | None = None,
    ) -> PrivacyRequestResult:
        require_permission(context, PERM_PRIVACY_APPROVE)
        request = self._get_scoped_request(context, request_id)
        approved_at = datetime.now(UTC)
        approval_id = self.repository.save_approval(
            {
                "tenant_id": context.tenant_id,
                "object_type": "privacy_request",
                "object_id": request_id,
                "approval_type": "controller_approval",
                "approved_by": context.actor_id,
                "status": "approved",
                "created_at": approved_at,
            }
        )
        result_summary = self._dict_value(request.get("result_summary"))
        result_summary["controller_approval"] = {
            "approval_id": approval_id,
            "approved_by": context.actor_id,
            "approved_at": approved_at.isoformat(),
            "note": approval_note,
            "status": "approved",
        }
        self.repository.update_privacy_request_status(
            request_id,
            "APPROVED",
            result_summary=result_summary,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="privacy.request.approve",
            object_type="privacy_request",
            object_id=request_id,
            result="success",
            request_id=context.request_id,
            metadata={"approval_id": approval_id},
        )
        self._enqueue_privacy_event(
            context,
            event_type="privacy.request.approved",
            object_type="privacy_request",
            object_id=request_id,
            payload={
                "approval_id": approval_id,
                "request_type": request["request_type"],
                "status": "APPROVED",
                "email_subject": "ComplyOS privacy request approved",
                "summary": f"Privacy request {request_id} was approved for processing.",
            },
        )
        created_at = request["created_at"]
        if not isinstance(created_at, datetime):
            raise ValueError(f"privacy request has invalid created_at: {request_id}")
        return PrivacyRequestResult(
            request_id=request_id,
            tenant_id=context.tenant_id,
            subject_id=str(request["subject_id"]),
            request_type=str(request["request_type"]),
            status="APPROVED",
            region=request["region"] if isinstance(request["region"], str) else None,
            created_at=created_at,
            actor_context=context.public_dict(),
        )

    def export_subject(self, context: ActorContext, request_id: str) -> DataSubjectExportResult:
        require_permission(context, PERM_PRIVACY_EXPORT)
        request = self._get_scoped_request(context, request_id)
        self._require_controller_approval(request)
        subject_id = str(request["subject_id"])
        exported = self.repository.get_subject_export(
            subject_id, tenant_id=context.tenant_id
        )
        record_counts = {
            "subject": 1 if exported["subject"] else 0,
            "learning_records": len(exported["learning_records"]),
            "enrollments": len(exported["enrollments"]),
        }
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="privacy.subject.export",
            object_type="privacy_request",
            object_id=request_id,
            result="success",
            request_id=context.request_id,
            metadata={"record_counts": record_counts},
        )
        return DataSubjectExportResult(
            request_id=request_id,
            tenant_id=context.tenant_id,
            subject_id=subject_id,
            status="EXPORTED",
            subject=exported["subject"],
            learning_records=exported["learning_records"],
            enrollments=exported["enrollments"],
            record_counts=record_counts,
            generated_at=datetime.now(UTC),
            actor_context=context.public_dict(),
        )

    def delete_subject(self, context: ActorContext, request_id: str) -> DeletionResult:
        require_permission(context, PERM_PRIVACY_DELETE)
        request = self._get_scoped_request(context, request_id)
        self._require_controller_approval(request)
        subject_id = str(request["subject_id"])
        holds = self.repository.list_active_legal_holds(
            tenant_id=context.tenant_id, subject_id=subject_id
        )
        if holds:
            hold_ids = [hold["id"] for hold in holds]
            result_summary = self._dict_value(request.get("result_summary"))
            result_summary["blocked_by_holds"] = hold_ids
            self.repository.update_privacy_request_status(
                request_id,
                "BLOCKED_LEGAL_HOLD",
                result_summary=result_summary,
            )
            self.repository.save_action_log(
                tenant_id=context.tenant_id,
                actor_id=context.actor_id,
                surface=context.surface,
                action="privacy.subject.delete",
                object_type="privacy_request",
                object_id=request_id,
                result="blocked_legal_hold",
                request_id=context.request_id,
                metadata=result_summary,
            )
            self._enqueue_privacy_event(
                context,
                event_type="privacy.delete.blocked_by_legal_hold",
                object_type="privacy_request",
                object_id=request_id,
                payload={
                    "subject_id": subject_id,
                    "blocked_by_holds": hold_ids,
                    "status": "BLOCKED_LEGAL_HOLD",
                    "email_subject": "ComplyOS deletion blocked by legal hold",
                    "summary": (
                        f"Deletion request {request_id} is blocked by active legal holds."
                    ),
                },
            )
            return DeletionResult(
                request_id=request_id,
                tenant_id=context.tenant_id,
                subject_id=subject_id,
                status="BLOCKED_LEGAL_HOLD",
                blocked_by_holds=hold_ids,
                actor_context=context.public_dict(),
            )

        deleted = self.repository.delete_subject_records(subject_id, tenant_id=context.tenant_id)
        completed_at = datetime.now(UTC)
        result_summary = self._dict_value(request.get("result_summary"))
        result_summary["deleted_records"] = deleted
        self.repository.update_privacy_request_status(
            request_id,
            "COMPLETED",
            closed_by=context.actor_id,
            completed_at=completed_at,
            result_summary=result_summary,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="privacy.subject.delete",
            object_type="privacy_request",
            object_id=request_id,
            result="success",
            request_id=context.request_id,
            metadata={"deleted_records": deleted},
        )
        self._enqueue_privacy_event(
            context,
            event_type="privacy.delete.completed",
            object_type="privacy_request",
            object_id=request_id,
            payload={
                "subject_id": subject_id,
                "deleted_records": deleted,
                "status": "COMPLETED",
                "email_subject": "ComplyOS deletion request completed",
                "summary": f"Deletion request {request_id} completed.",
            },
        )
        return DeletionResult(
            request_id=request_id,
            tenant_id=context.tenant_id,
            subject_id=subject_id,
            status="COMPLETED",
            deleted_records=deleted,
            completed_at=completed_at,
            actor_context=context.public_dict(),
        )

    def create_legal_hold(
        self,
        context: ActorContext,
        *,
        subject_id: str | None,
        scope: str,
        reason: str,
    ) -> LegalHoldResult:
        require_permission(context, PERM_LEGAL_HOLD_MANAGE)
        if scope not in {"subject", "tenant", "system"}:
            raise ValueError(f"unsupported legal hold scope: {scope}")
        if scope == "subject" and not subject_id:
            raise ValueError("subject legal hold requires subject_id")
        created_at = datetime.now(UTC)
        hold_id = str(uuid4())
        self.repository.save_legal_hold(
            {
                "id": hold_id,
                "tenant_id": context.tenant_id,
                "subject_id": subject_id,
                "scope": scope,
                "reason": reason,
                "status": "ACTIVE",
                "created_by": context.actor_id,
                "created_at": created_at,
            }
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="privacy.legal_hold.create",
            object_type="legal_hold",
            object_id=hold_id,
            result="success",
            request_id=context.request_id,
            metadata={"scope": scope},
        )
        self._enqueue_privacy_event(
            context,
            event_type="privacy.legal_hold.created",
            object_type="legal_hold",
            object_id=hold_id,
            payload={
                "scope": scope,
                "subject_id": subject_id,
                "status": "ACTIVE",
                "email_subject": "ComplyOS legal hold created",
                "summary": f"Legal hold {hold_id} was created with scope {scope}.",
            },
        )
        return LegalHoldResult(
            hold_id=hold_id,
            tenant_id=context.tenant_id,
            subject_id=subject_id,
            scope=scope,
            reason=reason,
            status="ACTIVE",
            created_at=created_at,
            actor_context=context.public_dict(),
        )

    def release_legal_hold(self, context: ActorContext, hold_id: str) -> LegalHoldResult:
        require_permission(context, PERM_LEGAL_HOLD_MANAGE)
        hold = self.repository.get_legal_hold(hold_id)
        if hold is None:
            raise ValueError(f"unknown legal hold: {hold_id}")
        if hold["tenant_id"] != context.tenant_id:
            raise PermissionError("cannot release legal hold for another tenant")
        released_at = datetime.now(UTC)
        self.repository.release_legal_hold(
            hold_id, released_by=context.actor_id, released_at=released_at
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="privacy.legal_hold.release",
            object_type="legal_hold",
            object_id=hold_id,
            result="success",
            request_id=context.request_id,
            metadata={"scope": hold["scope"]},
        )
        self._enqueue_privacy_event(
            context,
            event_type="privacy.legal_hold.released",
            object_type="legal_hold",
            object_id=hold_id,
            payload={
                "scope": hold["scope"],
                "subject_id": hold["subject_id"],
                "status": "RELEASED",
                "email_subject": "ComplyOS legal hold released",
                "summary": f"Legal hold {hold_id} was released.",
            },
        )
        return LegalHoldResult(
            hold_id=hold_id,
            tenant_id=context.tenant_id,
            subject_id=hold["subject_id"],
            scope=hold["scope"],
            reason=hold["reason"],
            status="RELEASED",
            created_at=hold["created_at"],
            released_at=released_at,
            actor_context=context.public_dict(),
        )

    def configure_retention_policy(
        self,
        context: ActorContext,
        *,
        raw_import_days: int,
        evidence_days: int,
        action_log_days: int,
        ai_proposal_days: int,
        privacy_request_days: int = 365,
    ) -> RetentionPolicyResult:
        require_permission(context, PERM_PRIVACY_RETENTION_MANAGE)
        values = {
            "raw_import_days": raw_import_days,
            "evidence_days": evidence_days,
            "action_log_days": action_log_days,
            "ai_proposal_days": ai_proposal_days,
            "privacy_request_days": privacy_request_days,
        }
        for key, value in values.items():
            if value < 1:
                raise ValueError(f"{key} must be positive")
        updated_at = datetime.now(UTC)
        self.repository.save_retention_policy(
            tenant_id=context.tenant_id,
            policy=values,
            updated_by=context.actor_id,
            updated_at=updated_at,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="privacy.retention.configure",
            object_type="retention_policy",
            object_id=context.tenant_id,
            result="success",
            request_id=context.request_id,
            metadata=values,
        )
        return RetentionPolicyResult(
            tenant_id=context.tenant_id,
            policy=values,
            updated_at=updated_at,
            actor_context=context.public_dict(),
        )

    def run_retention_cleanup(
        self,
        context: ActorContext,
        *,
        dry_run: bool = True,
    ) -> RetentionCleanupResult:
        require_permission(context, PERM_PRIVACY_RETENTION_MANAGE)
        policy = self.repository.get_retention_policy(context.tenant_id)
        if not policy:
            raise ValueError("configure a retention policy before running cleanup")
        normalized_policy = {key: int(value) for key, value in policy.items()}
        generated_at = datetime.now(UTC)
        privacy_request_days = normalized_policy.get("privacy_request_days", 365)
        raw_import_days = normalized_policy.get("raw_import_days", 30)
        ai_proposal_days = normalized_policy.get("ai_proposal_days", 180)
        evidence_days = normalized_policy.get("evidence_days", 2555)
        action_log_days = normalized_policy.get("action_log_days", 2555)
        cutoff_by_dataset = {
            "privacy_requests": generated_at - timedelta(days=privacy_request_days),
            "raw_import_rows": generated_at - timedelta(days=raw_import_days),
            "import_decisions": generated_at - timedelta(days=raw_import_days),
            "ai_proposals": generated_at - timedelta(days=ai_proposal_days),
            "evidence_ledger": generated_at - timedelta(days=evidence_days),
            "action_logs": generated_at - timedelta(days=action_log_days),
        }
        eligible_privacy_request_ids = self.repository.list_retention_eligible_privacy_request_ids(
            tenant_id=context.tenant_id,
            cutoff=cutoff_by_dataset["privacy_requests"],
        )
        eligible_import_batch_ids = self.repository.list_retention_eligible_import_batch_ids(
            tenant_id=context.tenant_id,
            cutoff=cutoff_by_dataset["raw_import_rows"],
        )
        eligible_ai_proposal_ids = self.repository.list_retention_eligible_ai_proposal_ids(
            tenant_id=context.tenant_id,
            cutoff=cutoff_by_dataset["ai_proposals"],
        )
        eligible_evidence_ids = self.repository.list_retention_eligible_evidence_ids(
            tenant_id=context.tenant_id,
            cutoff=cutoff_by_dataset["evidence_ledger"],
        )
        eligible_action_log_ids = self.repository.list_retention_eligible_action_log_ids(
            tenant_id=context.tenant_id,
            cutoff=cutoff_by_dataset["action_logs"],
        )
        eligible_counts = {
            "privacy_requests": len(eligible_privacy_request_ids),
            "raw_import_rows": self.repository.count_import_rows_for_batches(
                eligible_import_batch_ids
            ),
            "import_decisions": self.repository.count_import_decisions_for_batches(
                eligible_import_batch_ids
            ),
            "ai_proposals": len(eligible_ai_proposal_ids),
            "evidence_ledger": len(eligible_evidence_ids),
            "action_logs": len(eligible_action_log_ids),
        }
        cutoff_serialized = {key: value.isoformat() for key, value in cutoff_by_dataset.items()}
        if dry_run:
            deleted_counts = dict.fromkeys(eligible_counts, 0)
            # No destructive writes on a dry run, so a standalone audit log is safe.
            self.repository.save_action_log(
                tenant_id=context.tenant_id,
                actor_id=context.actor_id,
                surface=context.surface,
                action="privacy.retention.run",
                object_type="retention_policy",
                object_id=context.tenant_id,
                result="dry_run",
                request_id=context.request_id,
                metadata={
                    "dry_run": True,
                    "eligible_counts": eligible_counts,
                    "deleted_counts": deleted_counts,
                    "cutoff_by_dataset": cutoff_serialized,
                },
            )
        else:
            # Deletes + the "what was purged" audit record commit atomically, so a
            # partial failure can never destroy PII/evidence without an audit trail.
            deleted_counts = self.repository.purge_retention_eligible(
                tenant_id=context.tenant_id,
                privacy_request_ids=eligible_privacy_request_ids,
                import_batch_ids=eligible_import_batch_ids,
                ai_proposal_ids=eligible_ai_proposal_ids,
                evidence_ids=eligible_evidence_ids,
                action_log_ids=eligible_action_log_ids,
                actor_id=context.actor_id,
                surface=context.surface,
                request_id=context.request_id,
                log_metadata={
                    "dry_run": False,
                    "eligible_counts": eligible_counts,
                    "cutoff_by_dataset": cutoff_serialized,
                },
            )
        self._enqueue_privacy_event(
            context,
            event_type="privacy.retention.run",
            object_type="retention_policy",
            object_id=context.tenant_id,
            payload={
                "dry_run": dry_run,
                "eligible_counts": eligible_counts,
                "deleted_counts": deleted_counts,
                "email_subject": "ComplyOS retention cleanup run",
                "summary": (
                    "Retention cleanup completed as a dry run."
                    if dry_run
                    else "Retention cleanup completed and removed eligible records."
                ),
            },
        )
        return RetentionCleanupResult(
            tenant_id=context.tenant_id,
            dry_run=dry_run,
            policy=normalized_policy,
            cutoff_by_dataset=cutoff_by_dataset,
            eligible_counts=eligible_counts,
            deleted_counts=deleted_counts,
            generated_at=generated_at,
            actor_context=context.public_dict(),
        )

    def _enqueue_privacy_event(
        self,
        context: ActorContext,
        *,
        event_type: str,
        object_type: str,
        object_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        NotificationOutboxService(self.repository).enqueue_event(
            context,
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            payload=payload,
            channels=PRIVACY_NOTIFICATION_CHANNELS,
        )

    def _get_scoped_request(self, context: ActorContext, request_id: str) -> dict[str, object]:
        request = self.repository.get_privacy_request(request_id)
        if request is None:
            raise ValueError(f"unknown privacy request: {request_id}")
        if request["tenant_id"] != context.tenant_id:
            raise PermissionError("cannot access privacy request for another tenant")
        return request

    @staticmethod
    def _require_controller_approval(request: dict[str, object]) -> None:
        result_summary = request.get("result_summary")
        approval = (
            result_summary.get("controller_approval")
            if isinstance(result_summary, dict)
            else None
        )
        if isinstance(approval, dict) and approval.get("status") == "approved":
            return
        raise PermissionError("privacy request requires controller approval before processing")

    @staticmethod
    def _dict_value(value: object) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}
