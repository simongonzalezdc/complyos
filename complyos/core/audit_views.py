"""Shared presentation shaping for audit/remediation results.

The MCP tools and the FastAPI endpoints expose the same audit, report, and
remediation operations and must return the same JSON shapes. Centralizing the
shaping here keeps the surfaces in parity instead of each hand-building the
response dict (which let the API drift to no audit endpoints at all).
"""

from __future__ import annotations

from typing import Any

from complyos.models.domain import (
    AuditReport,
    ComplianceGap,
    EvidenceLedgerEntry,
    RemediationAction,
)


def shape_gaps(gaps: list[ComplianceGap], ledger: EvidenceLedgerEntry) -> dict[str, Any]:
    return {
        "gaps_found": len(gaps),
        "users_affected": len({g.user.id for g in gaps}),
        "evidence_hash": ledger.output_hash,
        "gaps": [
            {
                "user": {
                    "id": g.user.id,
                    "name": g.user.full_name,
                    "email": g.user.email,
                    "department": g.user.department,
                    "region": g.user.region,
                },
                "missing_courses": [c.title for c in g.missing_courses],
                "rule": g.rule_name,
                "days_overdue": g.days_overdue,
                "severity": g.severity,
            }
            for g in gaps
        ],
    }


def shape_report(report: AuditReport) -> dict[str, Any]:
    return {
        "generated_at": report.generated_at.isoformat(),
        "scope": report.scope,
        "total_users_audited": report.total_users_audited,
        "gaps_found": report.gaps_found,
        "gaps_by_severity": report.gaps_by_severity,
        "gaps_by_department": report.gaps_by_department,
        "top_missing_courses": report.top_missing_courses,
        "evidence_hash": report.evidence_hash,
    }


def shape_remediation(
    gaps: list[ComplianceGap],
    actions: list[RemediationAction],
    ledger: EvidenceLedgerEntry,
) -> dict[str, Any]:
    return {
        "gaps_found": len(gaps),
        "actions_taken": len(actions),
        "actions": [
            {
                "type": a.action_type,
                "user_id": a.user_id,
                "course_id": a.course_id,
                "status": a.status,
            }
            for a in actions
        ],
        "evidence_hash": ledger.output_hash,
    }
