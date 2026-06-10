"""MCP server exposing ComplyOS tools to AI agents."""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from complyos.connectors.base import LMSConnector
from complyos.connectors.csv_file import CSVConnector
from complyos.connectors.mock import MockConnector
from complyos.connectors.workday import WorkdayConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.remediation import RemediationEngine
from complyos.core.report_exporter import export_html
from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import AssignmentRule
from complyos.notification.sender import NotificationSender

mcp = FastMCP("complyos")

# Global auditor instance (initialized on first use)
_auditor: ComplianceAuditor | None = None


def _get_connector() -> LMSConnector:
    """Get the appropriate LMS connector based on environment."""
    if os.getenv("COMPLYOS_CSV_DIR"):
        return CSVConnector()
    if os.getenv("WORKDAY_BASE_URL"):
        return WorkdayConnector()
    return MockConnector()


def _get_notifier() -> NotificationSender | None:
    """Build a NotificationSender from environment or return None."""
    host = os.getenv("COMPLYOS_SMTP_HOST")
    port = int(os.getenv("COMPLYOS_SMTP_PORT", "587"))
    username = os.getenv("COMPLYOS_SMTP_USERNAME")
    password = os.getenv("COMPLYOS_SMTP_PASSWORD")
    from_addr = os.getenv("COMPLYOS_SMTP_FROM", "complyos@example.com")

    if host and username and password:
        return NotificationSender(
            host=host,
            port=port,
            username=username,
            password=password,
            from_address=from_addr,
        )
    return None


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
async def generate_compliance_digest(
    department: str | None = None,
    region: str | None = None,
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Generate a what-changed compliance digest vs the previous audit run.

    Runs a fresh audit, diffs it against the most recent snapshot for the
    same scope, and records the run so the next digest has a baseline.

    Args:
        department: Filter by department
        region: Filter by region
        db_path: SQLite database holding audit snapshot history

    Returns:
        New gaps, resolved gaps, trend (baseline/improving/worsening/flat),
        severity breakdown, and evidence hash.
    """
    from complyos.core.digest import DigestEngine

    engine = DigestEngine(_get_auditor(), LocalRepository(db_path))
    digest = await engine.generate(department=department, region=region)
    return digest.model_dump(mode="json")


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


@mcp.tool()
async def remediate_compliance_gaps(
    department: str | None = None,
    region: str | None = None,
    auto_remind: bool = True,
    auto_enroll: bool = False,
    notify_manager: bool = False,
) -> dict[str, Any]:
    """Audit and remediate compliance gaps in one operation.

    Runs a compliance audit, then applies remediation actions based on severity.

    Args:
        department: Filter by department
        region: Filter by region
        auto_remind: Send reminders for high/critical gaps
        auto_enroll: Auto-enroll users in missing courses
        notify_manager: Notify managers for critical gaps

    Returns:
        Summary of gaps found and remediation actions taken.
    """
    auditor = _get_auditor()
    gaps, ledger = await auditor.audit_gaps(department=department, region=region)

    connector = _get_connector()
    notifier = _get_notifier()
    engine = RemediationEngine(connector, notifier=notifier)
    actions = await engine.remediate_gaps(
        gaps,
        auto_remind=auto_remind,
        auto_enroll=auto_enroll,
        notify_manager=notify_manager,
    )

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


@mcp.tool()
async def export_audit_report_html(
    output_path: str = "report.html",
    department: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Export an audit report to a styled HTML file.

    Args:
        output_path: Where to save the HTML file
        department: Filter by department
        region: Filter by region

    Returns:
        Path to the generated file and report summary.
    """
    auditor = _get_auditor()
    report = await auditor.generate_report(department=department, region=region)
    path = export_html(report, output_path)
    return {
        "output_path": path,
        "gaps_found": report.gaps_found,
        "total_users": report.total_users_audited,
        "evidence_hash": report.evidence_hash,
    }


@mcp.tool()
async def export_compliance_dashboard(
    output_path: str = "dashboard.html",
    department: str | None = None,
    region: str | None = None,
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Generate a self-contained HTML compliance dashboard.

    Combines the current audit with snapshot history into a static file:
    summary cards, severity breakdown, department bars, gap-count trend,
    and a filterable gaps table. Read-only — does not record a snapshot.

    Args:
        output_path: Where to write the HTML file
        department: Filter by department
        region: Filter by region
        db_path: SQLite database holding audit snapshot history

    Returns:
        Path to the generated dashboard and summary stats.
    """
    from complyos.core.dashboard import generate_dashboard

    auditor = _get_auditor()
    report = await auditor.generate_report(department=department, region=region)
    history = LocalRepository(db_path).list_audit_snapshots(scope=report.scope)
    path = generate_dashboard(report, history=history, output_path=output_path)
    return {
        "dashboard_path": path,
        "scope": report.scope,
        "gaps_found": report.gaps_found,
        "history_points": len(history),
        "evidence_hash": report.evidence_hash,
    }


@mcp.tool()
async def send_notification(
    to_address: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    """Send a custom email notification.

    Args:
        to_address: Recipient email address
        subject: Email subject line
        body: Plain-text email body

    Returns:
        Dict with 'sent' boolean and optional 'error' string.
    """
    notifier = _get_notifier()
    if notifier is None:
        return {"sent": False, "error": "SMTP not configured"}
    return await notifier.send_email(to_address, subject, body)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
