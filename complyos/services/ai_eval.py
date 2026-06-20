"""Synthetic eval harness for the proposal-only AI provider.

Runs each of the five proposal tasks against the CONFIGURED provider on
synthetic, PII-free fixtures and grades the result on five checks per task:

1. ``reachable`` — the configured provider served the content (no fallback). For
   the deterministic provider this is trivially true; for a local model it is
   true only when the endpoint answered with a valid, schema-conformant reply.
2. ``valid_json`` — the stored proposal output is a structured JSON object.
3. ``schema_match`` — the output carries the per-task required fields and the
   proposal-only guardrail flags.
4. ``no_pii_leak`` — no email / SSN / phone-pattern appears anywhere in the
   serialized model output (the security-critical assertion).
5. ``quality`` — a basic non-emptiness + right-fields heuristic.

The fixtures are deliberately synthetic. The clustering/mapping fixtures do
embed real-looking PII *in the source input* so the eval also proves redaction
happens before the provider — but that PII must never survive into the output,
which check (4) enforces.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, Field

from complyos.services.ai_proposals import AIProposalResult, AIProposalService
from complyos.services.context import ActorContext

# Detectors for the PII-leak scan. Email and SSN mirror the redaction patterns.
# The phone detector requires >=10 digits so a legitimate ISO date (8 digits,
# e.g. a course deadline ``2026-09-01``) is not flagged as a phone number.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SSN_RE = re.compile(r"\b\d{3}[-.\s]\d{2}[-.\s]\d{4}\b")
_PHONE_RE = re.compile(r"\+?\d(?:[\d\s().-]*\d){9,}")

# Synthetic source rows for mapping/clustering. These carry real-looking PII in
# the INPUT on purpose; redaction must strip it before the provider sees it, and
# it must never appear in the OUTPUT (no_pii_leak proves redaction-before-model).
_SYNTHETIC_PII_ROWS: list[dict[str, Any]] = [
    {
        "Learner Name": "Dana Test",
        "Email": "dana.test@example.com",
        "Employee ID": "E-10001",
        "SSN": "111-22-3333",
        "Course ID": "SEC-101",
        "Status": "completed",
    },
    {
        "Learner Name": "Dana Test",
        "Email": "dana.test@example.com",
        "Employee ID": "E-10001",
        "SSN": "111-22-3333",
        "Course ID": "SEC-101",
        "Status": "completed",
    },
    {
        "Learner Name": "Sam Sample",
        "Email": "sam.sample@example.com",
        "Employee ID": "E-10002",
        "SSN": "444-55-6666",
        "Course ID": "SEC-102",
        "Status": "in_progress",
    },
]

# Raw PII strings expected to be absent from every model output.
_SYNTHETIC_RAW_PII: tuple[str, ...] = (
    "Dana Test",
    "dana.test@example.com",
    "E-10001",
    "111-22-3333",
    "Sam Sample",
    "sam.sample@example.com",
    "E-10002",
    "444-55-6666",
)


class TaskEval(BaseModel):
    """Result of evaluating one proposal task."""

    task: str
    reachable: bool
    valid_json: bool
    schema_match: bool
    no_pii_leak: bool
    quality: bool
    model_provider: str
    fallback: bool
    detail: str = ""

    @property
    def passed(self) -> bool:
        return all(
            (
                self.reachable,
                self.valid_json,
                self.schema_match,
                self.no_pii_leak,
                self.quality,
            )
        )


class EvalReport(BaseModel):
    """Aggregate eval result across all five tasks."""

    provider: str
    results: list[TaskEval] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.results) and all(r.passed for r in self.results)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passes(self) -> int:
        return sum(1 for r in self.results if r.passed)


def _scan_pii(output: dict[str, Any]) -> bool:
    """Return True when NO PII pattern or known raw value appears in ``output``."""
    serialized = json.dumps(output, default=str)
    if _EMAIL_RE.search(serialized) or _SSN_RE.search(serialized):
        return False
    if _PHONE_RE.search(serialized):
        return False
    return all(raw not in serialized for raw in _SYNTHETIC_RAW_PII)


def _evaluate(
    task: str,
    result: AIProposalResult,
    required_fields: tuple[str, ...],
    quality: bool,
) -> TaskEval:
    output = result.output
    fallback = bool(result.provenance.get("fallback", False))
    valid_json = isinstance(output, dict)
    schema_match = valid_json and all(field in output for field in required_fields)
    schema_match = schema_match and output.get("state_mutation_allowed") is False
    no_pii_leak = _scan_pii(output)
    detail = "" if not fallback else "provider unavailable; deterministic fallback used"
    return TaskEval(
        task=task,
        reachable=not fallback,
        valid_json=valid_json,
        schema_match=schema_match,
        no_pii_leak=no_pii_leak,
        quality=quality,
        model_provider=str(result.provenance.get("model_provider", "")),
        fallback=fallback,
        detail=detail,
    )


def run_eval(service: AIProposalService, context: ActorContext) -> EvalReport:
    """Run all five proposal tasks against the service's configured provider."""
    report = EvalReport(provider=service.provider.provider_id)

    # 1. field_mapping
    headers = list(_SYNTHETIC_PII_ROWS[0].keys())
    mapping = service.propose_mapping(
        context, headers=headers, sample_rows=_SYNTHETIC_PII_ROWS
    )
    mappings = mapping.output.get("suggested_mappings", {})
    quality = isinstance(mappings, dict) and set(mappings) == set(headers)
    report.results.append(
        _evaluate("field_mapping", mapping, ("target_schema", "suggested_mappings"), quality)
    )

    # 2. anomaly_summary
    anomaly = service.propose_anomaly_summary(
        context,
        issues=[{"code": "STALE_EXPORT"}, {"code": "BACKDATED_DATE"}, {"code": "BACKDATED_DATE"}],
    )
    summary = str(anomaly.output.get("summary", ""))
    quality = bool(summary.strip()) and anomaly.output.get("total_signals") == 3
    report.results.append(
        _evaluate("anomaly_summary", anomaly, ("summary", "counts_by_code"), quality)
    )

    # 3. gap_explanation
    gap = service.propose_gap_explanation(
        context,
        user_id="u-eval-1",
        department="Engineering",
        missing_courses=["Information Security Basics"],
        days_overdue=12,
        severity="high",
    )
    explanation = str(gap.output.get("explanation", ""))
    quality = "u-eval-1" in explanation and "Information Security Basics" in explanation
    report.results.append(
        _evaluate("gap_explanation", gap, ("user_id", "explanation"), quality)
    )

    # 4. remediation_message
    remediation = service.propose_remediation_message(
        context,
        user_id="u-eval-2",
        missing_courses=["Respectful Environment"],
        deadline="2026-09-01",
    )
    draft = str(remediation.output.get("message_draft", ""))
    quality = "u-eval-2" in draft and "Respectful Environment" in draft
    report.results.append(
        _evaluate("remediation_message", remediation, ("user_id", "message_draft"), quality)
    )

    # 5. duplicate_clustering
    clustering = service.propose_duplicate_clustering(context, rows=_SYNTHETIC_PII_ROWS)
    clusters = clustering.output.get("duplicate_clusters", [])
    quality = (
        isinstance(clusters, list)
        and clustering.output.get("rows_examined") == len(_SYNTHETIC_PII_ROWS)
    )
    report.results.append(
        _evaluate(
            "duplicate_clustering",
            clustering,
            ("duplicate_clusters", "rows_examined"),
            quality,
        )
    )

    return report
