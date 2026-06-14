"""Proposal-only AI assistance with provenance.

This layer can suggest mappings/explanations/drafts. It cannot mark learners
compliant, promote imports, execute remediation, or change assignment rules.

Hardening guarantees (WP15a):

- PII in any source input is redacted (`redact_pii`) BEFORE it can influence the
  ``input_hash``/``prompt_hash`` preimage or any model-facing payload. Only
  headers/structure and non-PII reach the hashed prompt.
- ``redaction_policy`` is a structured record of what was actually masked, not a
  static string.
- The service is deterministic. Adversarial content in source data (prompt
  injection) is inert: it can never change a proposal's status, auto-approve it,
  alter permissions, or escape into a control path.
- The class exposes NO method that mutates compliance state, and approval marks
  only the proposal approved — it never mutates LearningRecord/import/rule state.
- Proposals carry a reject + expiry lifecycle: PROPOSED -> APPROVED | REJECTED |
  EXPIRED. Expiry is computed at approval time (no background job required).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from complyos.connectors.normalization import ENROLLMENT_ALIASES
from complyos.connectors.normalization import normalize_header as _normalize_header
from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_AI_APPROVE,
    PERM_AI_PROPOSE,
    ActorContext,
    require_permission,
)

DEFAULT_AI_PROPOSAL_TTL_HOURS = 24

# Header-name fragments that mark a column as PII-bearing. Matched against the
# normalized (lowercased, separator-stripped) header.
_PII_HEADER_PARTS: tuple[str, ...] = (
    "name",
    "email",
    "phone",
    "ssn",
    "socialsecurity",
    "employeeid",
    "userid",
    "learnerid",
    "studentid",
    "address",
    "dob",
    "dateofbirth",
    "firstname",
    "lastname",
    "fullname",
)

# Value-level PII patterns (defense in depth, applied even when the header looks
# benign). Each pattern masks the whole value if it matches anywhere.
_PII_VALUE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # email
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\b\d{3}[.\s]\d{2}[.\s]\d{4}\b"),  # SSN with other separators
    re.compile(r"\b\+?\d[\d\s().-]{7,}\d\b"),  # phone-like
)

_MASK = "[REDACTED]"

# Policy stamped on proposal types that reference learners only by opaque,
# non-PII fields (user_id/department/course titles), so name/email/employee_id
# are excluded by construction rather than masked after the fact.
_PII_EXCLUDED_POLICY: dict[str, Any] = {
    "strategy": "pii_excluded_by_construction",
    "masked_fields": ["name", "email", "employee_id"],
    "masked_count": 0,
}


def _norm(value: Any) -> str:
    """Normalize a value into a stable lowercase match key (for clustering)."""
    return "" if value is None else " ".join(str(value).split()).strip().lower()


class AIProposalExpiredError(ValueError):
    """Raised when an AI proposal is approved after its TTL has elapsed."""

    def __init__(self, proposal_id: str) -> None:
        super().__init__(f"AI proposal expired and cannot be approved: {proposal_id}")
        self.proposal_id = proposal_id
        self.code = "ai_proposal_expired"


class AIProposalResult(BaseModel):
    proposal_id: str
    tenant_id: str
    proposal_type: str
    status: str
    input_hash: str
    output_hash: str
    output: dict[str, Any]
    provenance: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


def _header_is_pii(header: str) -> bool:
    normalized = _normalize_header(header)
    return any(part in normalized for part in _PII_HEADER_PARTS)


def _value_is_pii(value: str) -> bool:
    return any(pattern.search(value) for pattern in _PII_VALUE_PATTERNS)


def redact_pii(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mask PII in a single source row.

    Returns the redacted row plus a policy dict describing what was masked. A
    value is masked when its column header looks PII-bearing OR the value itself
    matches a PII pattern (defense in depth). Non-PII structure is preserved so
    the model still sees useful shape.
    """
    redacted: dict[str, Any] = {}
    masked_fields: list[str] = []
    for key, value in row.items():
        str_value = "" if value is None else str(value)
        if _header_is_pii(str(key)) or (str_value and _value_is_pii(str_value)):
            redacted[str(key)] = _MASK
            masked_fields.append(str(key))
        else:
            redacted[str(key)] = value
    policy = {
        "masked_fields": sorted(set(masked_fields)),
        "masked_count": len(masked_fields),
        "strategy": "header_and_value_pattern_masking",
    }
    return redacted, policy


def _redact_rows(
    rows: list[dict[str, Any]] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not rows:
        return [], {
            "sample_rows_redacted": False,
            "masked_fields": [],
            "masked_count": 0,
            "strategy": "headers_only_no_records",
        }
    redacted_rows: list[dict[str, Any]] = []
    masked_fields: set[str] = set()
    masked_count = 0
    for row in rows:
        redacted, policy = redact_pii(row)
        redacted_rows.append(redacted)
        masked_fields.update(policy["masked_fields"])
        masked_count += int(policy["masked_count"])
    return redacted_rows, {
        "sample_rows_redacted": True,
        "masked_fields": sorted(masked_fields),
        "masked_count": masked_count,
        "strategy": "header_and_value_pattern_masking",
    }


class AIProposalService:
    """Stores deterministic/proposal-only AI-style outputs and provenance."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()
        self._last_hash_preimage: dict[str, Any] = {}

    def last_hash_preimage(self) -> dict[str, Any]:
        """Return the (already-redacted) preimage used for the last input_hash.

        Exposed for verification/tests: it must never contain raw PII.
        """
        return self._last_hash_preimage

    def propose_mapping(
        self,
        context: ActorContext,
        *,
        headers: list[str],
        target_schema: str = "learning_records",
        sample_rows: list[dict[str, Any]] | None = None,
        model_provider: str = "deterministic-local",
        model_name: str = "rules-v1",
    ) -> AIProposalResult:
        require_permission(context, PERM_AI_PROPOSE)

        # Redact PII from any source rows BEFORE they influence the hash preimage
        # or the model-facing payload. Headers are non-PII column names; they are
        # treated as inert data (prompt injection cannot escape into a control
        # path because mapping is a deterministic alias lookup).
        redacted_rows, redaction_policy = _redact_rows(sample_rows)

        preimage = {
            "headers": headers,
            "target_schema": target_schema,
            "redacted_sample_rows": redacted_rows,
        }
        self._last_hash_preimage = preimage
        input_hash = _hash(preimage)

        suggestions = self._suggest_mappings(headers)
        output = {
            "target_schema": target_schema,
            "suggested_mappings": suggestions,
            "state_mutation_allowed": False,
            "requires_human_approval": True,
        }
        output_hash = _hash(output)
        proposal_id = str(uuid4())
        provenance = {
            "model_provider": model_provider,
            "model_name": model_name,
            "prompt_hash": _hash(
                {
                    "task": "field_mapping",
                    "target_schema": target_schema,
                    "headers": headers,
                    "redacted_sample_rows": redacted_rows,
                }
            ),
            "redaction_policy": redaction_policy,
            "response_hash": output_hash,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.repository.save_ai_proposal(
            {
                "id": proposal_id,
                "tenant_id": context.tenant_id,
                "proposal_type": "field_mapping",
                "input_hash": input_hash,
                "output_hash": output_hash,
                "status": "PROPOSED",
                "created_by": context.actor_id,
                "created_at": datetime.now(UTC),
                "output": output,
                "provenance": provenance,
            }
        )
        return AIProposalResult(
            proposal_id=proposal_id,
            tenant_id=context.tenant_id,
            proposal_type="field_mapping",
            status="PROPOSED",
            input_hash=input_hash,
            output_hash=output_hash,
            output=output,
            provenance=provenance,
            warnings=["proposal-only; cannot mutate compliance records"],
        )

    # ------------------------------------------------------------------
    # Additional deterministic, proposal-only types (WP15b)
    #
    # Each flows through the SAME store + provenance + approve/reject/expiry
    # lifecycle as propose_mapping and carries ``state_mutation_allowed: False``.
    # None of them name a learner by PII: drafts reference the opaque internal
    # ``user_id`` and non-PII fields (department, course titles, counts), and
    # duplicate clustering groups by a hash of the identity so the raw name/email
    # never reaches the stored output or the hash preimage.
    # ------------------------------------------------------------------
    def propose_anomaly_summary(
        self,
        context: ActorContext,
        *,
        issues: list[dict[str, Any]],
        model_name: str = "rules-v1",
    ) -> AIProposalResult:
        """Summarize anomaly signals (stale/backdated/duplicate counts) as a draft.

        Only each issue's ``code`` is read; messages/values are discarded so no
        record-level PII can reach the stored summary.
        """
        require_permission(context, PERM_AI_PROPOSE)
        codes = sorted(str(issue.get("code", "UNKNOWN")) for issue in issues)
        counts: dict[str, int] = {}
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
        total = len(codes)
        parts = [f"{count} {code}" for code, count in sorted(counts.items())]
        summary = (
            f"{total} anomaly signal(s): " + ", ".join(parts)
            if total
            else "no anomaly signals detected"
        )
        return self._store_proposal(
            context,
            proposal_type="anomaly_summary",
            model_name=model_name,
            input_preimage={"issue_codes": codes},
            output={
                "summary": summary,
                "counts_by_code": counts,
                "total_signals": total,
            },
            redaction_policy={
                "strategy": "codes_only_no_records",
                "masked_fields": [],
                "masked_count": 0,
            },
        )

    def propose_gap_explanation(
        self,
        context: ActorContext,
        *,
        user_id: str,
        department: str | None = None,
        missing_courses: list[str] | None = None,
        days_overdue: int | None = None,
        severity: str = "medium",
        model_name: str = "rules-v1",
    ) -> AIProposalResult:
        """Draft a plain-language explanation of one compliance gap (PII-free).

        Pass a gap's non-PII projection: its ``user.id``, ``user.department``,
        the missing course *titles*, ``days_overdue`` and ``severity``. The draft
        never references the learner's name or email.
        """
        require_permission(context, PERM_AI_PROPOSE)
        titles = list(missing_courses or [])
        course_clause = ", ".join(titles) if titles else "no outstanding courses"
        overdue_clause = (
            f" Overdue by {int(days_overdue)} day(s)."
            if days_overdue
            else " Not yet overdue."
        )
        explanation = (
            f"Learner {user_id} in {department or 'an unspecified department'} has "
            f"{len(titles)} outstanding mandatory course(s): {course_clause}."
            f"{overdue_clause} Severity: {severity}."
        )
        return self._store_proposal(
            context,
            proposal_type="gap_explanation",
            model_name=model_name,
            input_preimage={
                "user_id": user_id,
                "department": department,
                "missing_courses": titles,
                "days_overdue": days_overdue,
                "severity": severity,
            },
            output={
                "user_id": user_id,
                "department": department,
                "missing_courses": titles,
                "days_overdue": days_overdue,
                "severity": severity,
                "explanation": explanation,
            },
            redaction_policy=_PII_EXCLUDED_POLICY,
        )

    def propose_remediation_message(
        self,
        context: ActorContext,
        *,
        user_id: str,
        missing_courses: list[str] | None = None,
        deadline: str | None = None,
        model_name: str = "rules-v1",
    ) -> AIProposalResult:
        """Draft a reminder message for a learner's outstanding courses (PII-free).

        Addresses the learner by opaque ``user_id`` rather than name/email; the
        human approver personalizes and sends. Deterministic template.
        """
        require_permission(context, PERM_AI_PROPOSE)
        titles = list(missing_courses or [])
        course_clause = ", ".join(titles) if titles else "your assigned mandatory training"
        deadline_clause = (
            f" Please complete by {deadline}." if deadline else " Please complete it promptly."
        )
        message = (
            f"Reminder for learner {user_id}: you have {len(titles)} outstanding "
            f"mandatory course(s): {course_clause}.{deadline_clause}"
        )
        return self._store_proposal(
            context,
            proposal_type="remediation_message",
            model_name=model_name,
            input_preimage={
                "user_id": user_id,
                "missing_courses": titles,
                "deadline": deadline,
            },
            output={
                "user_id": user_id,
                "missing_courses": titles,
                "deadline": deadline,
                "message_draft": message,
            },
            redaction_policy=_PII_EXCLUDED_POLICY,
        )

    def propose_duplicate_clustering(
        self,
        context: ActorContext,
        *,
        rows: list[dict[str, Any]],
        model_name: str = "rules-v1",
    ) -> AIProposalResult:
        """Cluster likely-duplicate learner/course rows by a hashed identity key.

        PII in the input rows is redacted before hashing; the output exposes only
        a short identity *signature* (a hash, never the raw name/email) plus the
        row numbers in each cluster.
        """
        require_permission(context, PERM_AI_PROPOSE)
        redacted_rows, redaction_policy = _redact_rows(rows)
        clusters: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            emp = _norm(row.get("employee_id") or row.get("emp_id"))
            name = _norm(
                row.get("name")
                or f"{row.get('first_name', '')} {row.get('last_name', '')}"
            )
            course = _norm(row.get("course_id") or row.get("course"))
            identity = emp or (f"{name}|{course}" if name.strip() else "")
            if not identity.strip("|"):
                continue
            signature = _hash({"identity": identity})
            clusters.setdefault(signature, []).append(index)
        duplicate_clusters = [
            {"signature": signature[:16], "row_numbers": indexes, "size": len(indexes)}
            for signature, indexes in clusters.items()
            if len(indexes) > 1
        ]
        return self._store_proposal(
            context,
            proposal_type="duplicate_clustering",
            model_name=model_name,
            input_preimage={"redacted_sample_rows": redacted_rows},
            output={
                "duplicate_clusters": duplicate_clusters,
                "rows_examined": len(rows),
                "duplicate_groups": len(duplicate_clusters),
            },
            redaction_policy=redaction_policy,
        )

    def _store_proposal(
        self,
        context: ActorContext,
        *,
        proposal_type: str,
        model_name: str,
        input_preimage: dict[str, Any],
        output: dict[str, Any],
        redaction_policy: dict[str, Any],
    ) -> AIProposalResult:
        """Shared persistence path for the deterministic proposal types.

        Stamps the proposal-only guardrail flags, computes the provenance hashes,
        and stores the proposal as PROPOSED. Mirrors propose_mapping exactly.
        """
        self._last_hash_preimage = input_preimage
        input_hash = _hash(input_preimage)
        full_output = {
            **output,
            "state_mutation_allowed": False,
            "requires_human_approval": True,
        }
        output_hash = _hash(full_output)
        proposal_id = str(uuid4())
        provenance = {
            "model_provider": "deterministic-local",
            "model_name": model_name,
            "prompt_hash": _hash({"task": proposal_type, "input": input_preimage}),
            "redaction_policy": redaction_policy,
            "response_hash": output_hash,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.repository.save_ai_proposal(
            {
                "id": proposal_id,
                "tenant_id": context.tenant_id,
                "proposal_type": proposal_type,
                "input_hash": input_hash,
                "output_hash": output_hash,
                "status": "PROPOSED",
                "created_by": context.actor_id,
                "created_at": datetime.now(UTC),
                "output": full_output,
                "provenance": provenance,
            }
        )
        return AIProposalResult(
            proposal_id=proposal_id,
            tenant_id=context.tenant_id,
            proposal_type=proposal_type,
            status="PROPOSED",
            input_hash=input_hash,
            output_hash=output_hash,
            output=full_output,
            provenance=provenance,
            warnings=["proposal-only; cannot mutate compliance records"],
        )

    def approve(self, context: ActorContext, proposal_id: str) -> AIProposalResult:
        require_permission(context, PERM_AI_APPROVE)
        proposal = self._require_proposal(context, proposal_id)
        if proposal["status"] == "REJECTED":
            raise ValueError(f"rejected AI proposal cannot be approved: {proposal_id}")
        if proposal["status"] == "EXPIRED" or self._is_expired(proposal):
            self.repository.update_ai_proposal_status(proposal_id, "EXPIRED")
            raise AIProposalExpiredError(proposal_id)
        self.repository.update_ai_proposal_status(
            proposal_id,
            "APPROVED",
            approved_by=context.actor_id,
            approved_at=datetime.now(UTC),
        )
        self._log_action(context, proposal_id, action="ai.proposal.approve", reason=None)
        refreshed = self.repository.get_ai_proposal(proposal_id)
        assert refreshed is not None
        return self._to_result(
            refreshed,
            warnings=["approval records review; it still does not mutate compliance truth"],
        )

    def reject(
        self, context: ActorContext, proposal_id: str, reason: str
    ) -> AIProposalResult:
        require_permission(context, PERM_AI_APPROVE)
        proposal = self._require_proposal(context, proposal_id)
        if proposal["status"] == "APPROVED":
            raise ValueError(f"approved AI proposal cannot be rejected: {proposal_id}")
        self.repository.update_ai_proposal_status(proposal_id, "REJECTED")
        self._log_action(context, proposal_id, action="ai.proposal.reject", reason=reason)
        refreshed = self.repository.get_ai_proposal(proposal_id)
        assert refreshed is not None
        return self._to_result(
            refreshed,
            warnings=[f"proposal rejected: {reason}"],
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _require_proposal(
        self, context: ActorContext, proposal_id: str
    ) -> dict[str, Any]:
        proposal = self.repository.get_ai_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"unknown AI proposal: {proposal_id}")
        if proposal["tenant_id"] != context.tenant_id:
            raise PermissionError("cannot act on proposal for another tenant")
        return proposal

    @staticmethod
    def _ttl_hours() -> int:
        raw = os.environ.get("COMPLYOS_AI_PROPOSAL_TTL_HOURS")
        if not raw:
            return DEFAULT_AI_PROPOSAL_TTL_HOURS
        try:
            hours = int(raw)
        except ValueError:
            return DEFAULT_AI_PROPOSAL_TTL_HOURS
        return hours if hours > 0 else DEFAULT_AI_PROPOSAL_TTL_HOURS

    def _is_expired(self, proposal: dict[str, Any]) -> bool:
        created_at = proposal.get("created_at")
        if not isinstance(created_at, datetime):
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - created_at > timedelta(hours=self._ttl_hours())

    def _log_action(
        self,
        context: ActorContext,
        proposal_id: str,
        *,
        action: str,
        reason: str | None,
    ) -> None:
        metadata: dict[str, Any] = {}
        if reason is not None:
            metadata["reason"] = reason
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action=action,
            object_type="ai_proposal",
            object_id=proposal_id,
            result="ok",
            request_id=context.request_id,
            metadata=metadata,
        )

    @staticmethod
    def _to_result(
        proposal: dict[str, Any], *, warnings: list[str]
    ) -> AIProposalResult:
        return AIProposalResult(
            proposal_id=proposal["id"],
            tenant_id=proposal["tenant_id"],
            proposal_type=proposal["proposal_type"],
            status=proposal["status"],
            input_hash=proposal["input_hash"],
            output_hash=proposal["output_hash"],
            output=proposal.get("output") or {},
            provenance=proposal.get("provenance") or {},
            warnings=warnings,
        )

    @staticmethod
    def _suggest_mappings(headers: list[str]) -> dict[str, str | None]:
        aliases = {
            candidate: canonical
            for canonical, candidates in ENROLLMENT_ALIASES.items()
            for candidate in [_normalize_header(canonical), *candidates]
        }
        return {header: aliases.get(_normalize_header(header)) for header in headers}


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
