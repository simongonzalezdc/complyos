"""Compliance digest: diff the current audit against the previous run.

Answers the question a compliance manager actually asks each week:
"what changed?" — which gaps are new, which got resolved, and whether
the overall picture is improving or worsening.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from complyos.core.auditor import ComplianceAuditor
from complyos.core.repository import LocalRepository
from complyos.models.domain import AuditReport


class DigestEntry(BaseModel):
    """One (user, course) compliance gap, flattened for diffing."""

    user_id: str
    user_name: str
    user_email: str
    department: str
    course_code: str
    course_title: str
    severity: str


class ComplianceDigest(BaseModel):
    generated_at: datetime
    scope: str
    current_gaps: int
    previous_gaps: int | None = None
    previous_generated_at: datetime | None = None
    new_gaps: list[DigestEntry] = Field(default_factory=list)
    resolved_gaps: list[DigestEntry] = Field(default_factory=list)
    gaps_by_severity: dict[str, int] = Field(default_factory=dict)
    trend: str = "baseline"  # baseline | improving | worsening | flat
    evidence_hash: str
    snapshot_id: str


def _flatten_report(report: AuditReport) -> list[DigestEntry]:
    entries = []
    for gap in report.details:
        for course in gap.missing_courses:
            entries.append(
                DigestEntry(
                    user_id=gap.user.id,
                    user_name=gap.user.full_name,
                    user_email=gap.user.email,
                    department=gap.user.department,
                    course_code=course.code,
                    course_title=course.title,
                    severity=gap.severity,
                )
            )
    return entries


def _entry_key(entry: dict | DigestEntry) -> tuple[str, str]:
    if isinstance(entry, DigestEntry):
        return (entry.user_id, entry.course_code)
    return (entry["user_id"], entry["course_code"])


class DigestEngine:
    """Generates a compliance digest and records the run as a snapshot."""

    def __init__(self, auditor: ComplianceAuditor, repository: LocalRepository):
        self.auditor = auditor
        self.repository = repository

    async def generate(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> ComplianceDigest:
        report = await self.auditor.generate_report(department=department, region=region)
        current = _flatten_report(report)
        current_keys = {_entry_key(e) for e in current}

        previous = self.repository.get_latest_audit_snapshot(scope=report.scope)

        new_gaps: list[DigestEntry] = []
        resolved_gaps: list[DigestEntry] = []
        trend = "baseline"
        previous_count: int | None = None
        previous_at: datetime | None = None

        if previous is not None:
            previous_entries = [DigestEntry(**g) for g in previous["gaps"]]
            previous_keys = {_entry_key(e) for e in previous_entries}
            new_gaps = [e for e in current if _entry_key(e) not in previous_keys]
            resolved_gaps = [e for e in previous_entries if _entry_key(e) not in current_keys]
            previous_count = len(previous_entries)
            previous_at = previous["generated_at"]
            if len(current) < previous_count:
                trend = "improving"
            elif len(current) > previous_count:
                trend = "worsening"
            else:
                trend = "flat"

        snapshot_id = self.repository.save_audit_snapshot(
            scope=report.scope,
            generated_at=report.generated_at,
            gaps_found=len(current),
            gaps=[e.model_dump() for e in current],
            gaps_by_severity=report.gaps_by_severity,
            evidence_hash=report.evidence_hash,
        )

        return ComplianceDigest(
            generated_at=report.generated_at,
            scope=report.scope,
            current_gaps=len(current),
            previous_gaps=previous_count,
            previous_generated_at=previous_at,
            new_gaps=new_gaps,
            resolved_gaps=resolved_gaps,
            gaps_by_severity=report.gaps_by_severity,
            trend=trend,
            evidence_hash=report.evidence_hash,
            snapshot_id=snapshot_id,
        )
