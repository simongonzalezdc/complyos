"""AI-use-policy attestation and AI-literacy requirement tracking.

This service lets an organization track *human-recorded* evidence that each
learner read and accepted a named AI-use policy version (or completed an
AI-literacy item), as a first-class requirement that flows through the existing
audit -> gap -> evidence -> readiness pipeline:

- **Requirement**: an attestation requirement is a ``Course`` (learning item)
  whose ``category`` is an :class:`AttestationCategory` and which is
  ``mandatory``. The auditor (``complyos/core/auditor.py``) already treats a
  learner with no completed/met record for a mandatory item as a
  ``ComplianceGap`` — so an un-attested learner surfaces as a gap with no new
  audit engine.
- **Evidence**: recording an attestation writes a normalized ``LearningRecord``
  (status COMPLETED) *and* an immutable evidence-ledger entry (who/what/when +
  policy version, hashed) atomically. Annual re-attestation is expressed with
  ``expires_at``, so the same expiry-reminder/BI surfaces built earlier pick it
  up with no extra wiring.

Human-not-AI boundary: recording is gated by ``attestation:record``, which the
proposal-only ``agent_service_account`` role deliberately lacks. An attestation
is a statement that a *person* accepted a policy; the AI/proposal layer can read
attestation state (to report un-attested learners) but can never mark a learner
attested.

Claim boundary: language here is attestation / readiness / evidence. Recording
an attestation never asserts a learner is "certified" or "compliant".
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from uuid import uuid4

from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    AttestationCategory,
    AttestationRecord,
    Course,
    LearningRecord,
    LearningRecordStatus,
)
from complyos.services.context import (
    PERM_ATTESTATION_READ,
    PERM_ATTESTATION_RECORD,
    PERM_RULES_WRITE,
    ActorContext,
    require_permission,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AttestationService:
    """Authorization-gated attestation requirement definition + recording."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def define_requirement(
        self,
        context: ActorContext,
        *,
        course_id: str,
        code: str,
        title: str,
        category: AttestationCategory | str,
        description: str | None = None,
    ) -> Course:
        """Define an attestation-type requirement as a mandatory learning item.

        Writing a mandatory learning item is a policy-configuration action, so it
        is gated at ``rules:write`` (the same gate as assignment-rule authoring).
        The resulting ``Course`` is mandatory and carries an attestation category,
        so the auditor counts a learner without a met record for it as a gap.
        """
        require_permission(context, PERM_RULES_WRITE)
        resolved = self._coerce_category(category)
        course = Course(
            id=course_id,
            code=code,
            title=title,
            description=description,
            mandatory=True,
            category=resolved.value,
        )
        self.repository.save_course(course)
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="attestation.requirement.define",
            object_type="course",
            object_id=course_id,
            result="success",
            request_id=context.request_id,
            metadata={"category": resolved.value, "code": code},
        )
        return course

    def record(
        self,
        context: ActorContext,
        *,
        user_id: str,
        requirement_id: str,
        policy_version: str,
        attested_at: datetime | None = None,
        expires_at: date | None = None,
        on_behalf: bool = False,
    ) -> AttestationRecord:
        """Record that a learner attested to a named policy version.

        This is human-recorded evidence, gated at ``attestation:record`` (which
        the proposal-only agent role lacks). The learner may self-attest, or an
        admin may record on the learner's behalf — either way the *recording*
        actor is captured in evidence (``recorded_by`` + ``recorded_on_behalf``).
        Writes a completed/met ``LearningRecord`` and an evidence-ledger entry in
        one atomic transaction.
        """
        require_permission(context, PERM_ATTESTATION_RECORD)

        requirement = self.repository.get_course(requirement_id)
        if requirement is None:
            raise ValueError(f"unknown attestation requirement: {requirement_id}")
        if requirement.category is None or not requirement.is_attestation_requirement:
            raise ValueError(
                f"learning item {requirement_id} is not an attestation requirement "
                f"(category={requirement.category!r})"
            )
        category = AttestationCategory(requirement.category)

        # Tenant scope: the learner must belong to the recording tenant. Resolving
        # the owner here (and refusing a cross-tenant learner) prevents a context
        # scoped to tenant A from attesting a learner owned by tenant B.
        learner = self.repository.get_user(user_id)
        if learner is None:
            raise ValueError(f"unknown learner: {user_id}")
        learner_tenant = (learner.custom_attributes or {}).get("tenant_id", "local-default")
        if learner_tenant != context.tenant_id:
            raise PermissionError("cannot attest a learner owned by another tenant")

        policy_version = policy_version.strip()
        if not policy_version:
            raise ValueError("policy_version is required to record an attestation")

        attested = attested_at or datetime.now(UTC)
        record_id = str(uuid4())
        # The policy version + recording provenance live on the typed payload, not
        # a loose dict on the hot path — they are the substance of the evidence.
        source_payload: dict[str, str | bool] = {
            "attestation_category": category.value,
            "policy_version": policy_version,
            "recorded_by": context.actor_id,
            "recorded_on_behalf": on_behalf,
            "attested_at": attested.isoformat(),
        }
        record = LearningRecord(
            id=record_id,
            user_id=user_id,
            course_id=requirement_id,
            source_system="attestation",
            source_record_id=record_id,
            status=LearningRecordStatus.COMPLETED,
            assigned_date=attested,
            completed_date=attested,
            completion_percentage=100.0,
            expires_at=expires_at,
            raw_source_hash=_sha256(
                json.dumps(
                    {
                        "user_id": user_id,
                        "requirement_id": requirement_id,
                        "policy_version": policy_version,
                        "attested_at": attested.isoformat(),
                    },
                    sort_keys=True,
                )
            ),
            source_payload=source_payload,
        )

        output_summary = (
            f"Learner {user_id} attested to {requirement.code} "
            f"(policy {policy_version}, category {category.value})"
        )
        output_hash = _sha256(
            json.dumps(
                {
                    "learning_record_id": record_id,
                    "user_id": user_id,
                    "requirement_id": requirement_id,
                    "policy_version": policy_version,
                    "category": category.value,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                sort_keys=True,
            )
        )
        evidence_id = self.repository.record_attestation(
            record=record,
            tenant_id=context.tenant_id,
            evidence_entry={
                "timestamp": attested,
                "query_type": "attestation.record",
                "query_params": {
                    "tenant_id": context.tenant_id,
                    "user_id": user_id,
                    "requirement_id": requirement_id,
                    "category": category.value,
                },
                "raw_data_hash": record.raw_source_hash,
                "transformation_steps": [
                    "verified_attestation_requirement",
                    "verified_learner_tenant_scope",
                    "recorded_human_attestation",
                    "learning_record_upserted",
                ],
                "output_hash": output_hash,
                "output_summary": output_summary,
            },
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="attestation.record",
            object_type="learning_record",
            object_id=record_id,
            result="success",
            request_id=context.request_id,
            metadata={
                "requirement_id": requirement_id,
                "category": category.value,
                "policy_version": policy_version,
                "on_behalf": on_behalf,
                "evidence_id": evidence_id,
            },
        )
        return AttestationRecord(
            learning_record_id=record_id,
            evidence_id=evidence_id,
            tenant_id=context.tenant_id,
            learner_id=user_id,
            requirement_id=requirement_id,
            requirement_code=requirement.code,
            category=category,
            policy_version=policy_version,
            attested_at=attested,
            recorded_by=context.actor_id,
            recorded_on_behalf=on_behalf,
            expires_at=expires_at,
            output_hash=output_hash,
        )

    def list_attestations(
        self,
        context: ActorContext,
        *,
        user_id: str | None = None,
        requirement_id: str | None = None,
    ) -> list[AttestationRecord]:
        """List recorded attestations for the tenant (``attestation:read``).

        Tenant-scoped via ``list_learning_records_with_owner`` (which filters on
        the record's ``tenant_id``); only attestation-sourced records are
        returned, so a regular course completion is never mistaken for one.
        """
        require_permission(context, PERM_ATTESTATION_READ)
        rows = self.repository.list_learning_records_with_owner(tenant_id=context.tenant_id)
        results: list[AttestationRecord] = []
        for record, _user, course in rows:
            if record.source_system != "attestation":
                continue
            if course.category is None or not course.is_attestation_requirement:
                continue
            if user_id is not None and record.user_id != user_id:
                continue
            if requirement_id is not None and record.course_id != requirement_id:
                continue
            payload = record.source_payload or {}
            attested_raw = payload.get("attested_at")
            attested_at = (
                datetime.fromisoformat(str(attested_raw))
                if attested_raw
                else (record.completed_date or datetime.now(UTC))
            )
            results.append(
                AttestationRecord(
                    learning_record_id=record.id,
                    evidence_id="",
                    tenant_id=context.tenant_id,
                    learner_id=record.user_id,
                    requirement_id=record.course_id,
                    requirement_code=course.code,
                    category=AttestationCategory(course.category),
                    policy_version=str(payload.get("policy_version", "")),
                    attested_at=attested_at,
                    recorded_by=str(payload.get("recorded_by", "")),
                    recorded_on_behalf=bool(payload.get("recorded_on_behalf", False)),
                    expires_at=record.expires_at,
                    output_hash=record.raw_source_hash or "",
                )
            )
        results.sort(key=lambda r: (r.learner_id, r.requirement_code))
        return results

    @staticmethod
    def _coerce_category(category: AttestationCategory | str) -> AttestationCategory:
        if isinstance(category, AttestationCategory):
            return category
        try:
            return AttestationCategory(category)
        except ValueError as exc:
            valid = ", ".join(sorted(AttestationCategory.values()))
            raise ValueError(
                f"unknown attestation category {category!r}; expected one of: {valid}"
            ) from exc
