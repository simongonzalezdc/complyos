"""Domain<->ORM serialization mappers for the repository.

Extracted from the repository module so the persistence class is not dominated
by ~330 lines of pure row-shaping. These are stateless static methods; the
repository inherits them via RepositoryMappers, so callers still use
``self._to_*`` exactly as before.
"""

from __future__ import annotations

import json
from typing import Any

from complyos.models.database import (
    DBAIProposal,
    DBAIProvenance,
    DBAuditActionLog,
    DBCourse,
    DBEnrollment,
    DBEvidenceLedger,
    DBImportBatch,
    DBImportDecision,
    DBImportRow,
    DBInboundWebhookEvent,
    DBIntakeRequest,
    DBLearningRecord,
    DBLegalHold,
    DBNotificationDelivery,
    DBNotificationEvent,
    DBNotificationPreference,
    DBPrivacyRequest,
    DBRosterSnapshot,
    DBSourceIntelJobExecution,
    DBSourceIntelProposal,
    DBSourceIntelSchedule,
    DBUser,
)
from complyos.models.domain import (
    Course,
    Enrollment,
    IntakePriority,
    IntakeStatus,
    LearningRecord,
    LearningRecordStatus,
    PrivacyRequest,
    PrivacyRequestType,
    RosterSnapshot,
    RosterStatus,
    TrainingRequest,
    User,
)


class RepositoryMappers:
    """Mixin of stateless ORM-row -> dict/domain-model mappers."""

    @staticmethod
    def _to_user(db: DBUser) -> User:
        from complyos.models.domain import EmploymentStatus

        return User(
            id=db.id,
            employee_id=db.employee_id,
            email=db.email,
            first_name=db.first_name,
            last_name=db.last_name,
            department=db.department,
            region=db.region or "",
            hire_date=db.hire_date,
            employment_status=EmploymentStatus(db.employment_status),
            manager_id=db.manager_id,
            custom_attributes=db.custom_attributes or {},
        )

    @staticmethod
    def _to_training_request(db: DBIntakeRequest) -> TrainingRequest:
        return TrainingRequest(
            id=db.id,
            tenant_id=db.tenant_id,
            requester=db.requester,
            title=db.title,
            audience=db.audience,
            priority=IntakePriority(db.priority) if db.priority else None,
            business_context=db.business_context,
            constraints=db.constraints,
            requested_by_date=db.requested_by_date,
            status=IntakeStatus(db.status),
            created_by=db.created_by,
            created_at=db.created_at,
            confirmed_by=db.confirmed_by,
            confirmed_at=db.confirmed_at,
            confirmation_note=db.confirmation_note,
        )

    @staticmethod
    def _to_roster_snapshot(db: DBRosterSnapshot) -> RosterSnapshot:
        return RosterSnapshot(
            id=db.id,
            tenant_id=db.tenant_id,
            label=db.label,
            source_system=db.source_system,
            batch_id=db.batch_id,
            status=RosterStatus(db.status),
            created_by=db.created_by,
            created_at=db.created_at,
            approved_by=db.approved_by,
            approved_at=db.approved_at,
            approval_note=db.approval_note,
        )

    @staticmethod
    def _to_course(db: DBCourse) -> Course:
        return Course(
            id=db.id,
            code=db.code,
            title=db.title,
            description=db.description,
            duration_minutes=db.duration_minutes,
            mandatory=db.mandatory,
            category=db.category,
        )

    @staticmethod
    def _to_enrollment(db: DBEnrollment) -> Enrollment:
        from complyos.models.domain import EnrollmentStatus

        return Enrollment(
            id=db.id,
            user_id=db.user_id,
            course_id=db.course_id,
            status=EnrollmentStatus(db.status),
            assigned_date=db.assigned_date,
            due_date=db.due_date,
            completed_date=db.completed_date,
            completion_percentage=db.completion_percentage,
            score=db.score,
        )

    @staticmethod
    def _to_learning_record(db: DBLearningRecord) -> LearningRecord:
        return LearningRecord(
            id=db.id,
            user_id=db.user_id,
            course_id=db.course_id,
            source_system=db.source_system,
            source_record_id=db.source_record_id,
            status=LearningRecordStatus(db.status),
            assigned_date=db.assigned_date,
            due_date=db.due_date,
            completed_date=db.completed_date,
            completion_percentage=db.completion_percentage,
            score=db.score,
            exempt=db.exempt,
            expires_at=db.expires_at,
            raw_source_hash=db.raw_source_hash,
            source_payload=db.source_payload or {},
        )

    @staticmethod
    def _to_evidence_dict(db: DBEvidenceLedger) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "timestamp": db.timestamp,
            "query_type": db.query_type,
            "query_params": json.loads(db.query_params or "{}"),
            "raw_data_hash": db.raw_data_hash,
            "transformation_steps": json.loads(db.transformation_steps or "[]"),
            "output_hash": db.output_hash,
            "output_summary": db.output_summary,
        }

    @staticmethod
    def _to_action_log_dict(db: DBAuditActionLog) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "actor_id": db.actor_id,
            "surface": db.surface,
            "action": db.action,
            "object_type": db.object_type,
            "object_id": db.object_id,
            "result": db.result,
            "request_id": db.request_id,
            "redacted_metadata": db.redacted_metadata or {},
            "created_at": db.created_at,
        }

    @staticmethod
    def _to_import_batch_dict(db: DBImportBatch) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "source_system": db.source_system,
            "profile": db.profile,
            "raw_file_hash": db.raw_file_hash,
            "status": db.status,
            "idempotency_key": db.idempotency_key,
            "created_by": db.created_by,
            "promoted_by": db.promoted_by,
            "created_at": db.created_at,
            "promoted_at": db.promoted_at,
            "metadata": db.batch_metadata or {},
        }

    @staticmethod
    def _to_import_row_dict(db: DBImportRow) -> dict[str, Any]:
        return {
            "id": db.id,
            "batch_id": db.batch_id,
            "row_number": db.row_number,
            "normalized_payload": db.normalized_payload or {},
            "raw_payload_hash": db.raw_payload_hash,
            "validation_status": db.validation_status,
            "rejection_codes": db.rejection_codes or [],
            "source_record_id": db.source_record_id,
            "issues": db.issues or [],
        }

    @staticmethod
    def _to_import_decision_dict(db: DBImportDecision) -> dict[str, Any]:
        return {
            "id": db.id,
            "batch_id": db.batch_id,
            "row_id": db.row_id,
            "decision_type": db.decision_type,
            "decision_payload": db.decision_payload or {},
            "decided_by": db.decided_by,
            "decided_at": db.decided_at,
            "reason": db.reason,
        }

    @staticmethod
    def _to_ai_proposal_dict(
        proposal: DBAIProposal,
        provenance: DBAIProvenance | None,
    ) -> dict[str, Any]:
        return {
            "id": proposal.id,
            "tenant_id": proposal.tenant_id,
            "proposal_type": proposal.proposal_type,
            "input_hash": proposal.input_hash,
            "output_hash": proposal.output_hash,
            "status": proposal.status,
            "created_by": proposal.created_by,
            "approved_by": proposal.approved_by,
            "created_at": proposal.created_at,
            "approved_at": proposal.approved_at,
            "output": proposal.output or {},
            "provenance": provenance.usage_metadata if provenance else {},
        }

    @staticmethod
    def _to_source_intel_proposal_dict(db: DBSourceIntelProposal) -> dict[str, Any]:
        payload = dict(db.payload or {})
        raw_signal = payload.get("signal")
        signal: dict[str, Any] = raw_signal if isinstance(raw_signal, dict) else {}
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "run_id": db.run_id,
            "adapter_name": db.adapter_name,
            "signal_type": db.signal_type,
            "source_id": db.source_id,
            "source_url": db.source_url,
            "source_hash": db.source_hash,
            "approval_state": db.approval_state,
            "decided_by": db.decided_by,
            "decided_at": db.decided_at,
            "created_at": db.created_at,
            "title": signal.get("title"),
            "summary": signal.get("summary"),
            "score": signal.get("score"),
            "payload": payload,
        }

    @staticmethod
    def _to_source_intel_schedule_dict(db: DBSourceIntelSchedule) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "name": db.name,
            "query": db.query,
            "source_ids": db.source_ids or [],
            "interval_hours": db.interval_hours,
            "mode": db.mode,
            "status": db.status,
            "created_by": db.created_by,
            "last_run_at": db.last_run_at,
            "created_at": db.created_at,
        }

    @staticmethod
    def _to_source_intel_job_execution_dict(db: DBSourceIntelJobExecution) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "schedule_id": db.schedule_id,
            "run_id": db.run_id,
            "status": db.status,
            "started_at": db.started_at,
            "finished_at": db.finished_at,
            "summary": db.summary or {},
            "error": db.error,
            "created_by": db.created_by,
        }

    @staticmethod
    def _to_notification_event_dict(
        db: DBNotificationEvent,
        *,
        delivery_count: int | None = None,
    ) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "event_type": db.event_type,
            "source": db.source,
            "object_type": db.object_type,
            "object_id": db.object_id,
            "payload": db.payload or {},
            "payload_hash": db.payload_hash,
            "status": db.status,
            "created_by": db.created_by,
            "created_at": db.created_at,
            "delivery_count": delivery_count,
        }

    @staticmethod
    def _to_notification_delivery_dict(
        db: DBNotificationDelivery,
        event: DBNotificationEvent | None,
    ) -> dict[str, Any]:
        event_payload = (
            RepositoryMappers._to_notification_event_dict(event) if event is not None else None
        )
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "event_id": db.event_id,
            "channel": db.channel,
            "destination_ref": db.destination_ref,
            "status": db.status,
            "attempts": db.attempts,
            "max_attempts": db.max_attempts,
            "next_attempt_at": db.next_attempt_at,
            "last_error": db.last_error,
            "response_metadata": db.response_metadata or {},
            "sent_at": db.sent_at,
            "created_at": db.created_at,
            "updated_at": db.updated_at,
            "event": event_payload,
        }

    @staticmethod
    def _to_notification_preference_dict(
        db: DBNotificationPreference,
    ) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "channel": db.channel,
            "event_type": db.event_type,
            "enabled": db.enabled,
            "reason": db.reason,
            "updated_by": db.updated_by,
            "updated_at": db.updated_at,
        }

    @staticmethod
    def _to_inbound_webhook_event_dict(db: DBInboundWebhookEvent) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "source": db.source,
            "event_type": db.event_type,
            "object_type": db.object_type,
            "object_id": db.object_id,
            "payload": db.payload or {},
            "payload_hash": db.payload_hash,
            "signature_valid": db.signature_valid,
            "status": db.status,
            "header_metadata": db.header_metadata or {},
            "received_by": db.received_by,
            "received_at": db.received_at,
        }

    @staticmethod
    def _to_privacy_request(db: DBPrivacyRequest) -> PrivacyRequest:
        return PrivacyRequest(
            id=db.id,
            tenant_id=db.tenant_id,
            subject_id=db.subject_id,
            request_type=PrivacyRequestType(db.request_type),
            status=db.status,
            region=db.region,
            opened_by=db.opened_by,
            closed_by=db.closed_by,
            created_at=db.created_at,
            completed_at=db.completed_at,
            metadata=db.request_metadata or {},
            result_summary=db.result_summary or {},
        )

    @staticmethod
    def _to_legal_hold_dict(db: DBLegalHold) -> dict[str, Any]:
        return {
            "id": db.id,
            "tenant_id": db.tenant_id,
            "subject_id": db.subject_id,
            "scope": db.scope,
            "reason": db.reason,
            "status": db.status,
            "created_by": db.created_by,
            "released_by": db.released_by,
            "created_at": db.created_at,
            "released_at": db.released_at,
            "metadata": db.hold_metadata or {},
        }
