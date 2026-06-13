"""Privacy program persistence: DSR requests, legal holds, retention.

Extracted from LocalRepository so the compliance-critical privacy/retention
deletion logic has a single cohesive home where erasure completeness and
legal-hold interactions can be reasoned about and tested as a unit. Mixed into
LocalRepository, so callers keep using ``repository.<method>`` unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from complyos.core.repository_base import (
    _TENANT_WIDE_HOLD_SCOPES,
    HoldDecision,
    RepositoryBase,
)
from complyos.core.repository_mappers import RepositoryMappers
from complyos.core.time import utc_now
from complyos.models.database import (
    DBAIProposal,
    DBAIProvenance,
    DBApproval,
    DBAuditActionLog,
    DBCourse,
    DBEnrollment,
    DBEvidenceLedger,
    DBImportBatch,
    DBImportDecision,
    DBImportRow,
    DBLearningRecord,
    DBLegalHold,
    DBPrivacyRequest,
    DBRetentionPolicy,
    DBUser,
)


class PrivacyRepositoryMixin(RepositoryBase, RepositoryMappers):
    """Privacy/DSR, legal-hold, and retention persistence for LocalRepository."""

    # ------------------------------------------------------------------
    # Privacy program workflows
    # ------------------------------------------------------------------
    def save_privacy_request(self, request: dict[str, Any]) -> None:
        with self._session() as session:
            session.add(
                DBPrivacyRequest(
                    id=request["id"],
                    tenant_id=request["tenant_id"],
                    subject_id=request["subject_id"],
                    request_type=request["request_type"],
                    status=request.get("status", "OPEN"),
                    region=request.get("region"),
                    opened_by=request["opened_by"],
                    created_at=request.get("created_at") or utc_now(),
                    request_metadata=request.get("metadata") or {},
                    result_summary=request.get("result_summary") or {},
                )
            )
            session.commit()

    def get_privacy_request(self, request_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            request = session.get(DBPrivacyRequest, request_id)
            return self._to_privacy_request_dict(request) if request else None

    def update_privacy_request_status(
        self,
        request_id: str,
        status: str,
        *,
        closed_by: str | None = None,
        completed_at: datetime | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        with self._session() as session:
            request = session.get(DBPrivacyRequest, request_id)
            if request is None:
                return
            request.status = status
            if closed_by is not None:
                request.closed_by = closed_by
            if completed_at is not None:
                request.completed_at = completed_at
            if result_summary is not None:
                request.result_summary = result_summary
            session.commit()

    def save_approval(self, approval: dict[str, Any]) -> str:
        approval_id = approval.get("id") or str(uuid.uuid4())
        with self._session() as session:
            session.add(
                DBApproval(
                    id=approval_id,
                    tenant_id=approval["tenant_id"],
                    object_type=approval["object_type"],
                    object_id=approval["object_id"],
                    approval_type=approval["approval_type"],
                    approved_by=approval.get("approved_by"),
                    status=approval.get("status", "approved"),
                    created_at=approval.get("created_at") or utc_now(),
                )
            )
            session.commit()
        return approval_id

    def get_subject_export(self, subject_id: str, *, tenant_id: str) -> dict[str, Any]:
        with self._session() as session:
            # Tenant scoping is a real, indexed column on every PII table — no
            # fallback. A subject (and their records) is only visible to the
            # tenant that owns them, so one tenant cannot export another's data.
            user = session.get(DBUser, subject_id)
            if user is not None and user.tenant_id != tenant_id:
                user = None
            learning_records = (
                session.query(DBLearningRecord)
                .where(
                    DBLearningRecord.user_id == subject_id,
                    DBLearningRecord.tenant_id == tenant_id,
                )
                .all()
                if user is not None
                else []
            )
            enrollments = (
                session.query(DBEnrollment)
                .where(
                    DBEnrollment.user_id == subject_id,
                    DBEnrollment.tenant_id == tenant_id,
                )
                .all()
                if user is not None
                else []
            )
            return {
                "subject": self._to_user(user).model_dump(mode="json") if user else {},
                "learning_records": [
                    self._to_learning_record(record).model_dump(mode="json")
                    for record in learning_records
                ],
                "enrollments": [
                    self._to_enrollment(enrollment).model_dump(mode="json")
                    for enrollment in enrollments
                ],
            }

    def delete_subject_records(self, subject_id: str, *, tenant_id: str) -> dict[str, int]:
        with self._session() as session:
            # Erasure is tenant-scoped on the indexed tenant_id column: a caller
            # can only delete a subject and the records owned by their own tenant.
            user = session.get(DBUser, subject_id)
            if user is None or user.tenant_id != tenant_id:
                return {"users": 0, "learning_records": 0, "enrollments": 0}

            learning_records = (
                session.query(DBLearningRecord)
                .where(
                    DBLearningRecord.user_id == subject_id,
                    DBLearningRecord.tenant_id == tenant_id,
                )
                .delete(synchronize_session=False)
            )
            enrollments = (
                session.query(DBEnrollment)
                .where(
                    DBEnrollment.user_id == subject_id,
                    DBEnrollment.tenant_id == tenant_id,
                )
                .delete(synchronize_session=False)
            )
            # Complete the erasure: the subject's raw identifiers also live in
            # import rows (normalized_payload.user_id), so a "COMPLETED" deletion
            # must remove those too. Notification events and the count-only audit
            # action logs are intentionally retained as process-audit evidence
            # that the workflow happened; those are governed by retention cleanup.
            import_rows = self._delete_subject_import_rows(session, subject_id, tenant_id=tenant_id)
            session.delete(user)
            session.commit()
            return {
                "users": 1,
                "learning_records": learning_records,
                "enrollments": enrollments,
                "import_rows": import_rows,
            }

    @staticmethod
    def _delete_subject_import_rows(session: Session, subject_id: str, *, tenant_id: str) -> int:
        """Delete import rows whose normalized payload carries the subject id.

        Import rows link to a batch (tenant-scoped) and hold the subject id inside
        a JSON payload, so we resolve the tenant's batches and filter in Python to
        stay portable across SQLite and PostgreSQL JSON dialects.
        """
        batch_ids = [
            row[0]
            for row in session.query(DBImportBatch.id)
            .where(DBImportBatch.tenant_id == tenant_id)
            .all()
        ]
        if not batch_ids:
            return 0
        deleted = 0
        rows = session.query(DBImportRow).where(DBImportRow.batch_id.in_(batch_ids)).all()
        for row in rows:
            payload = row.normalized_payload or {}
            if payload.get("user_id") == subject_id:
                session.delete(row)
                deleted += 1
        return deleted

    def save_legal_hold(self, hold: dict[str, Any]) -> None:
        with self._session() as session:
            session.add(
                DBLegalHold(
                    id=hold["id"],
                    tenant_id=hold["tenant_id"],
                    subject_id=hold.get("subject_id"),
                    scope=hold["scope"],
                    reason=hold["reason"],
                    status=hold.get("status", "ACTIVE"),
                    created_by=hold["created_by"],
                    created_at=hold.get("created_at") or utc_now(),
                    hold_metadata=hold.get("metadata") or {},
                )
            )
            session.commit()

    def get_legal_hold(self, hold_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            hold = session.get(DBLegalHold, hold_id)
            return self._to_legal_hold_dict(hold) if hold else None

    def list_active_legal_holds(
        self,
        *,
        tenant_id: str,
        subject_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBLegalHold).where(
                DBLegalHold.tenant_id == tenant_id,
                DBLegalHold.status == "ACTIVE",
            )
            if subject_id is not None:
                # A subject's deletion is blocked by a hold naming that subject OR
                # by any tenant-wide/system-wide hold. Omitting "system" here was a
                # spoliation gap: a system hold silently failed to block deletion.
                query = query.where(
                    (DBLegalHold.subject_id == subject_id)
                    | (DBLegalHold.scope.in_(_TENANT_WIDE_HOLD_SCOPES))
                )
            return [self._to_legal_hold_dict(row) for row in query.all()]

    def resolve_active_holds(self, *, tenant_id: str) -> HoldDecision:
        """Evaluate all active holds for a tenant once, for uniform enforcement.

        Returns whether a tenant-wide/system hold blocks everything, plus the set
        of subject ids under a subject-scoped hold. Every retention-eligibility
        query routes through this so the scope vocabulary cannot drift again.
        """
        with self._session() as session:
            active = (
                session.query(DBLegalHold)
                .where(DBLegalHold.tenant_id == tenant_id, DBLegalHold.status == "ACTIVE")
                .all()
            )
        tenant_blocked = any(hold.scope in _TENANT_WIDE_HOLD_SCOPES for hold in active)
        held_subject_ids = frozenset(
            hold.subject_id
            for hold in active
            if hold.subject_id and hold.scope == "subject"
        )
        return HoldDecision(tenant_blocked=tenant_blocked, held_subject_ids=held_subject_ids)

    def release_legal_hold(
        self,
        hold_id: str,
        *,
        released_by: str,
        released_at: datetime,
    ) -> None:
        with self._session() as session:
            hold = session.get(DBLegalHold, hold_id)
            if hold is None:
                return
            hold.status = "RELEASED"
            hold.released_by = released_by
            hold.released_at = released_at
            session.commit()

    def save_retention_policy(
        self,
        *,
        tenant_id: str,
        policy: dict[str, Any],
        updated_by: str,
        updated_at: datetime,
    ) -> None:
        with self._session() as session:
            row = session.get(DBRetentionPolicy, tenant_id)
            if row is None:
                row = DBRetentionPolicy(tenant_id=tenant_id, updated_by=updated_by)
                session.add(row)
            row.policy = policy
            row.updated_by = updated_by
            row.updated_at = updated_at
            session.commit()

    def get_retention_policy(self, tenant_id: str) -> dict[str, Any]:
        with self._session() as session:
            row = session.get(DBRetentionPolicy, tenant_id)
            return dict(row.policy or {}) if row else {}

    def list_retention_eligible_privacy_request_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        closed_statuses = {"COMPLETED", "REJECTED", "CANCELLED"}
        holds = self.resolve_active_holds(tenant_id=tenant_id)
        if holds.tenant_blocked:
            return []
        with self._session() as session:
            candidates = (
                session.query(DBPrivacyRequest.id, DBPrivacyRequest.subject_id)
                .where(
                    DBPrivacyRequest.tenant_id == tenant_id,
                    DBPrivacyRequest.created_at < cutoff,
                    DBPrivacyRequest.status.in_(closed_statuses),
                )
                .all()
            )
        # Privacy requests carry subject_id, so we can exclude held subjects
        # precisely rather than blocking the whole dataset.
        return [row.id for row in candidates if row.subject_id not in holds.held_subject_ids]

    def list_retention_eligible_import_batch_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        terminal_statuses = {"PROMOTED", "REJECTED", "EXPIRED", "PROMOTION_FAILED"}
        # Import batches have no indexed subject linkage, so any active hold of any
        # scope fails closed: never purge while a hold exists rather than risk
        # deleting a held subject's raw source payloads.
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBImportBatch.id)
                .where(
                    DBImportBatch.tenant_id == tenant_id,
                    DBImportBatch.created_at < cutoff,
                    DBImportBatch.status.in_(terminal_statuses),
                )
                .all()
            )
            return [row[0] for row in rows]

    def count_import_rows_for_batches(self, batch_ids: list[str]) -> int:
        if not batch_ids:
            return 0
        with self._session() as session:
            return session.query(DBImportRow).where(DBImportRow.batch_id.in_(batch_ids)).count()

    def count_import_decisions_for_batches(self, batch_ids: list[str]) -> int:
        if not batch_ids:
            return 0
        with self._session() as session:
            return (
                session.query(DBImportDecision)
                .where(DBImportDecision.batch_id.in_(batch_ids))
                .count()
            )

    def list_retention_eligible_ai_proposal_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        disposable_statuses = {"REJECTED", "EXPIRED", "CANCELLED"}
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBAIProposal.id)
                .where(
                    DBAIProposal.tenant_id == tenant_id,
                    DBAIProposal.created_at < cutoff,
                    DBAIProposal.status.in_(disposable_statuses),
                )
                .all()
            )
            return [row[0] for row in rows]

    def list_retention_eligible_evidence_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBEvidenceLedger.id)
                .where(
                    DBEvidenceLedger.tenant_id == tenant_id,
                    DBEvidenceLedger.timestamp < cutoff,
                )
                .all()
            )
            return [row[0] for row in rows]

    def list_retention_eligible_action_log_ids(
        self,
        *,
        tenant_id: str,
        cutoff: datetime,
    ) -> list[str]:
        if self.resolve_active_holds(tenant_id=tenant_id).any_active:
            return []
        with self._session() as session:
            rows = (
                session.query(DBAuditActionLog.id)
                .where(
                    DBAuditActionLog.tenant_id == tenant_id,
                    DBAuditActionLog.created_at < cutoff,
                )
                .all()
            )
            return [row[0] for row in rows]

    def purge_retention_eligible(
        self,
        *,
        tenant_id: str,
        privacy_request_ids: list[str],
        import_batch_ids: list[str],
        ai_proposal_ids: list[str],
        evidence_ids: list[str],
        action_log_ids: list[str],
        actor_id: str,
        surface: str,
        request_id: str | None,
        log_metadata: dict[str, Any],
    ) -> dict[str, int]:
        """Delete all retention-eligible records AND write the audit record atomically.

        Every destructive delete plus the ``privacy.retention.run`` audit-log entry
        commit (or roll back) together in one transaction. This closes the
        chain-of-custody gap where a mid-sequence failure could leave PII/evidence
        irreversibly destroyed with no audit trail of what was removed. Each DELETE
        is tenant-scoped (defense in depth) so a wrong id list cannot reach across
        tenants. Returns the per-dataset deleted counts.
        """

        def _delete(session: Session, model: Any, ids: list[str], *, tenant_scoped: bool) -> int:
            if not ids:
                return 0
            clause = model.id.in_(ids)
            if tenant_scoped:
                clause = clause & (model.tenant_id == tenant_id)
            return (
                session.query(model)
                .where(clause)
                .delete(synchronize_session=False)
            )

        with self._session() as session:
            try:
                deleted_import_decisions = 0
                deleted_import_rows = 0
                if import_batch_ids:
                    deleted_import_decisions = (
                        session.query(DBImportDecision)
                        .where(DBImportDecision.batch_id.in_(import_batch_ids))
                        .delete(synchronize_session=False)
                    )
                    deleted_import_rows = (
                        session.query(DBImportRow)
                        .where(DBImportRow.batch_id.in_(import_batch_ids))
                        .delete(synchronize_session=False)
                    )
                if ai_proposal_ids:
                    session.query(DBAIProvenance).where(
                        DBAIProvenance.proposal_id.in_(ai_proposal_ids)
                    ).delete(synchronize_session=False)
                deleted_counts = {
                    "privacy_requests": _delete(
                        session, DBPrivacyRequest, privacy_request_ids, tenant_scoped=True
                    ),
                    "raw_import_rows": deleted_import_rows,
                    "import_decisions": deleted_import_decisions,
                    "ai_proposals": _delete(
                        session, DBAIProposal, ai_proposal_ids, tenant_scoped=True
                    ),
                    "evidence_ledger": _delete(
                        session, DBEvidenceLedger, evidence_ids, tenant_scoped=True
                    ),
                    "action_logs": _delete(
                        session, DBAuditActionLog, action_log_ids, tenant_scoped=True
                    ),
                }
                session.add(
                    DBAuditActionLog(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        actor_id=actor_id,
                        surface=surface,
                        action="privacy.retention.run",
                        object_type="retention_policy",
                        object_id=tenant_id,
                        result="success",
                        request_id=request_id,
                        redacted_metadata={**log_metadata, "deleted_counts": deleted_counts},
                        created_at=utc_now(),
                    )
                )
                session.commit()
                return deleted_counts
            except Exception:
                session.rollback()
                raise

    def clear_all(self) -> None:
        with self._session() as session:
            session.query(DBEnrollment).delete()
            session.query(DBLearningRecord).delete()
            session.query(DBCourse).delete()
            session.query(DBUser).delete()
            session.query(DBEvidenceLedger).delete()
            session.query(DBImportDecision).delete()
            session.query(DBImportRow).delete()
            session.query(DBImportBatch).delete()
            session.query(DBAIProvenance).delete()
            session.query(DBAIProposal).delete()
            session.query(DBApproval).delete()
            session.query(DBPrivacyRequest).delete()
            session.query(DBLegalHold).delete()
            session.query(DBRetentionPolicy).delete()
            session.commit()

