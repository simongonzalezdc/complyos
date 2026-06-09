"""MCP server exposing ComplyOS tools to AI agents."""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from complyos.connectors.base import LMSConnector
from complyos.connectors.mock import MockConnector
from complyos.connectors.workday import WorkdayConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import AssignmentRule

mcp = FastMCP("complyos")

# Global auditor instance (initialized on first use)
_auditor: ComplianceAuditor | None = None


def _get_connector() -> LMSConnector:
    """Get the appropriate LMS connector based on environment."""
    if os.getenv("WORKDAY_BASE_URL"):
        return WorkdayConnector()
    return MockConnector()


def _get_auditor() -> ComplianceAuditor:
    global _auditor
    if _auditor is None:
        _auditor = ComplianceAuditor(_get_connector())
    return _auditor


@mcp.tool()
async def audit_compliance_gaps(
    department: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Audit compliance training gaps across the organization.

    Finds users who are missing required training assignments.
    Optionally filter by department or region.

    Args:
        department: Filter by department name (e.g. "Engineering", "HR")
        region: Filter by region (e.g. "US", "MX")

    Returns:
        Summary of gaps found with user details and missing courses.
    """
    auditor = _get_auditor()
    gaps, ledger = await auditor.audit_gaps(department=department, region=region)

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


@mcp.tool()
async def get_user_compliance_status(user_id: str) -> dict[str, Any]:
    """Get complete compliance status for a single user.

    Args:
        user_id: The user's ID in the LMS

    Returns:
        User details, course-by-course status, and compliance summary.
    """
    auditor = _get_auditor()
    return await auditor.get_user_status(user_id)


@mcp.tool()
async def generate_audit_report(
    department: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Generate a structured compliance audit report.

    Creates an evidence-backed report suitable for leadership review
    or regulatory audit submission.

    Args:
        department: Filter by department
        region: Filter by region

    Returns:
        Structured report with severity breakdown, department analysis,
        top missing courses, and evidence hash.
    """
    auditor = _get_auditor()
    report = await auditor.generate_report(department=department, region=region)

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


@mcp.tool()
async def check_connector_health() -> dict[str, Any]:
    """Check the health of the LMS connector.

    Returns:
        Connector status, authentication state, and any errors.
    """
    connector = _get_connector()
    return await connector.health_check()


@mcp.tool()
async def validate_assignment_rule(
    name: str,
    target_criteria: dict[str, Any],
    course_ids: list[str],
    deadline_days: int = 30,
) -> dict[str, Any]:
    """Validate an assignment rule before deployment.

    Checks for unknown courses, empty targets, and users who would match.

    Args:
        name: Rule name
        target_criteria: Filters like {"department": "Engineering"}
        course_ids: List of course IDs to assign
        deadline_days: Days until deadline

    Returns:
        Validation result with valid flag, issues list, and preview.
    """
    repo = LocalRepository()
    engine = AssignmentRuleEngine(repo)
    rule = AssignmentRule(
        name=name,
        target_criteria=target_criteria,
        course_ids=course_ids,
        deadline_days_from_trigger=deadline_days,
    )
    return engine.validate_rule(rule)


@mcp.tool()
async def preview_assignment_rule(
    name: str,
    target_criteria: dict[str, Any],
    course_ids: list[str],
    deadline_days: int = 30,
) -> dict[str, Any]:
    """Preview which users would be affected by an assignment rule.

    Args:
        name: Rule name
        target_criteria: Filters like {"department": "Engineering"}
        course_ids: List of course IDs to assign
        deadline_days: Days until deadline

    Returns:
        Affected users, missing courses, and total enrollment count.
    """
    repo = LocalRepository()
    engine = AssignmentRuleEngine(repo)
    rule = AssignmentRule(
        name=name,
        target_criteria=target_criteria,
        course_ids=course_ids,
        deadline_days_from_trigger=deadline_days,
    )
    return engine.preview_rule(rule)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
