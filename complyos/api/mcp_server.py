"""MCP server exposing ComplyOS tools to AI agents."""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from complyos.config import ComplyOSConfig, resolve_env_placeholder
from complyos.connectors.base import LMSConnector
from complyos.connectors.cornerstone import CornerstoneConnector
from complyos.connectors.csv_file import CSVConnector
from complyos.connectors.mock import MockConnector
from complyos.connectors.successfactors import SuccessFactorsConnector
from complyos.connectors.workday import WorkdayConnector
from complyos.core.audit_views import shape_gaps, shape_remediation, shape_report
from complyos.core.auditor import ComplianceAuditor
from complyos.core.report_exporter import export_html
from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import AssignmentRule
from complyos.notification.sender import NotificationSender, build_notifier_from_env
from complyos.services.ai_proposals import AIProposalService
from complyos.services.audit import AuditService
from complyos.services.context import (
    PERM_AUDIT_READ,
    PERM_CONNECTORS_READ,
    PERM_RULES_PREVIEW,
    ROLE_PERMISSIONS,
    ActorContext,
    default_local_context,
    require_permission,
)
from complyos.services.evidence import EvidenceService
from complyos.services.governance import GovernancePacketService
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.privacy import PrivacyProgramService
from complyos.services.readiness import ReadinessService
from complyos.services.remediation import RemediationService
from complyos.services.security_evidence import SecurityEvidenceService

mcp = FastMCP("complyos")

# Least-privileged default role for an MCP (AI-agent) caller. Proposal-only:
# can audit, preview, and propose, but NOT delete subjects, approve controller
# decisions, promote imports, or auto-remediate. Operators raise this explicitly
# via COMPLYOS_MCP_ROLE when an MCP service account genuinely needs more.
DEFAULT_MCP_ROLE = "agent_service_account"

# Global auditor instance (initialized on first use)
_auditor: ComplianceAuditor | None = None
_auditor_signature: tuple[Any, ...] | None = None


def _mcp_context(*, track: str = "workforce") -> ActorContext:
    """Build the actor context for an MCP call, defaulting to least privilege.

    Routing every MCP tool through one context (instead of self-assigning
    privacy_admin/owner inline) enforces the "AI is proposal-only" guardrail at
    the surface boundary: privileged services fail closed unless the operator
    opts up with COMPLYOS_MCP_ROLE.
    """
    role = os.getenv("COMPLYOS_MCP_ROLE", DEFAULT_MCP_ROLE)
    if role not in ROLE_PERMISSIONS:
        raise ValueError(f"unknown COMPLYOS_MCP_ROLE: {role!r}")
    return default_local_context(surface="mcp", track=track, role=role)


def _workday_from_config(config: ComplyOSConfig) -> WorkdayConnector:
    workday_config = config.connector.get("workday", {})
    return WorkdayConnector(
        base_url=resolve_env_placeholder(workday_config.get("base_url")),
        username=resolve_env_placeholder(workday_config.get("username")),
        password=resolve_env_placeholder(workday_config.get("password")),
    )


def _successfactors_from_config(config: ComplyOSConfig) -> SuccessFactorsConnector:
    connector_config = config.connector.get("successfactors", {})
    return SuccessFactorsConnector(
        base_url=resolve_env_placeholder(connector_config.get("base_url")),
        client_id=resolve_env_placeholder(connector_config.get("client_id")),
        client_secret=resolve_env_placeholder(connector_config.get("client_secret")),
        company_id=resolve_env_placeholder(connector_config.get("company_id")),
        user_id=resolve_env_placeholder(connector_config.get("user_id")),
        token_url=resolve_env_placeholder(connector_config.get("token_url")),
    )


def _cornerstone_from_config(config: ComplyOSConfig) -> CornerstoneConnector:
    connector_config = config.connector.get("cornerstone", {})
    return CornerstoneConnector(
        base_url=resolve_env_placeholder(connector_config.get("base_url")),
        client_id=resolve_env_placeholder(connector_config.get("client_id")),
        client_secret=resolve_env_placeholder(connector_config.get("client_secret")),
        token_url=resolve_env_placeholder(connector_config.get("token_url")),
    )


def _get_connector() -> LMSConnector:
    """Get the appropriate LMS connector from env first, then config."""
    if os.getenv("COMPLYOS_CSV_DIR"):
        return CSVConnector()
    if os.getenv("WORKDAY_BASE_URL"):
        return WorkdayConnector()

    config = ComplyOSConfig.load()
    connector_config = config.connector
    connector_type = str(connector_config.get("type", "")).strip().lower()
    if connector_type == "csv":
        return CSVConnector(connector_config.get("csv_dir"))
    if connector_type == "workday":
        return _workday_from_config(config)
    if connector_type == "successfactors":
        return _successfactors_from_config(config)
    if connector_type == "cornerstone":
        return _cornerstone_from_config(config)
    return MockConnector()


def _connector_signature(connector: LMSConnector) -> tuple[Any, ...]:
    return (
        connector.name,
        str(getattr(connector, "data_dir", "")),
        getattr(connector, "base_url", ""),
        getattr(connector, "username", ""),
    )


def _get_notifier() -> NotificationSender | None:
    """Build a NotificationSender from environment or return None."""
    return build_notifier_from_env()


def _get_auditor() -> ComplianceAuditor:
    global _auditor, _auditor_signature
    connector = _get_connector()
    signature = _connector_signature(connector)
    if _auditor is None or _auditor_signature != signature:
        _auditor = ComplianceAuditor(connector)
        _auditor_signature = signature
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
    gaps, ledger = await AuditService(_get_connector()).run_audit(
        _mcp_context(), department=department, region=region
    )
    return shape_gaps(gaps, ledger)


@mcp.tool()
async def get_user_compliance_status(user_id: str) -> dict[str, Any]:
    """Get complete compliance status for a single user.

    Args:
        user_id: The user's ID in the LMS

    Returns:
        User details, course-by-course status, and compliance summary.
    """
    return await AuditService(_get_connector()).get_status(_mcp_context(), user_id=user_id)


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
    report = await AuditService(_get_connector()).generate_report(
        _mcp_context(), department=department, region=region
    )
    return shape_report(report)


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
    digest = await AuditService(_get_connector(), LocalRepository(db_path)).get_digest(
        _mcp_context(), department=department, region=region
    )
    return digest.model_dump(mode="json")


@mcp.tool()
async def check_connector_health() -> dict[str, Any]:
    """Check the health of the LMS connector.

    Returns:
        Connector status, authentication state, and any errors.
    """
    require_permission(_mcp_context(), PERM_CONNECTORS_READ)
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
    require_permission(_mcp_context(), PERM_RULES_PREVIEW)
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
    require_permission(_mcp_context(), PERM_RULES_PREVIEW)
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
    # Mutating remediation (reminders, auto-enroll, manager notifications) must
    # be explicitly authorized; the proposal-only default role cannot execute it.
    # RemediationService.execute owns the remediation:execute check.
    gaps, actions, ledger = await RemediationService(
        _get_connector(), notifier=_get_notifier()
    ).execute(
        _mcp_context(),
        department=department,
        region=region,
        auto_remind=auto_remind,
        auto_enroll=auto_enroll,
        notify_manager=notify_manager,
    )
    return shape_remediation(gaps, actions, ledger)


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
    require_permission(_mcp_context(), PERM_AUDIT_READ)
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
    require_permission(_mcp_context(), PERM_AUDIT_READ)
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


@mcp.tool()
async def check_readiness(db_path: str = "complyos.db") -> dict[str, Any]:
    """Read-only: check enterprise/school readiness controls without making compliance claims.

    Args:
        db_path: SQLite database path.

    Returns:
        Readiness posture, control statuses, global watchlist, and forbidden claim language.
    """
    context = _mcp_context()
    return ReadinessService(LocalRepository(db_path)).check(context).model_dump(mode="json")


@mcp.tool()
async def preview_import_batch(
    csv_text: str,
    source_system: str = "csv",
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Read-only/proposal-gated: preview and quarantine CSV rows before promotion.

    This does not mutate active learning records. Bad rows fail closed and require
    explicit decisions before promotion.

    Args:
        csv_text: CSV content to preview.
        source_system: Source system label.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        Import batch id, validation counts, issues, and can_promote flag.
    """
    context = _mcp_context(track=profile)
    request = ImportPreviewRequest(
        source_system=source_system,
        profile=profile,
        csv_text=csv_text,
    )
    return ImportService(LocalRepository(db_path)).preview(context, request).model_dump(mode="json")


@mcp.tool()
async def promote_import_batch(
    batch_id: str,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Mutating: promote a validated import batch into active learning records.

    Promotion requires service-layer permission and blocks if rows are rejected,
    pending, or need a decision.

    Args:
        batch_id: Import batch ID returned by preview_import_batch.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        Promotion status, promoted row count, blocked row count, and evidence id.
    """
    context = _mcp_context(track=profile)
    return (
        ImportService(LocalRepository(db_path))
        .promote(context, batch_id)
        .model_dump(mode="json")
    )


@mcp.tool()
async def decide_import_row(
    batch_id: str,
    row_id: str,
    decision_type: str,
    reason: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Mutating metadata: record an explicit import-row decision.

    Args:
        batch_id: Import batch ID returned by preview_import_batch.
        row_id: Import row ID from the preview result.
        decision_type: accept, reject, map_field, merge_duplicate, ignore_row,
            or require_manual_review.
        reason: Optional human-readable decision reason.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        Decision result and resulting row status.
    """
    context = _mcp_context(track=profile)
    return (
        ImportService(LocalRepository(db_path))
        .decide(
            context,
            batch_id=batch_id,
            row_id=row_id,
            decision_type=decision_type,
            reason=reason,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
async def list_evidence_ledger(
    db_path: str = "complyos.db",
    tenant_id: str = "local-default",
    limit: int = 50,
) -> dict[str, Any]:
    """Read-only: list evidence ledger entries and hashes.

    Args:
        db_path: SQLite database path.
        tenant_id: Tenant scope for ledger entries.
        limit: Maximum ledger entries to return.

    Returns:
        Evidence ledger entries.
    """
    context = _mcp_context()
    context = context.model_copy(update={"tenant_id": tenant_id})
    return {
        "items": EvidenceService(_get_connector(), LocalRepository(db_path)).list_ledger(
            context,
            limit=limit,
        )
    }


@mcp.tool()
async def propose_field_mapping(
    headers: list[str],
    target_schema: str = "learning_records",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Proposal-only: suggest CSV/header mappings with stored provenance.

    The proposal cannot promote imports, mark compliance, or mutate records.

    Args:
        headers: Source CSV headers to map.
        target_schema: Target schema name.
        db_path: SQLite database path.

    Returns:
        Proposal id, suggested mappings, hashes, and provenance.
    """
    context = _mcp_context()
    return AIProposalService(LocalRepository(db_path)).propose_mapping(
        context,
        headers=headers,
        target_schema=target_schema,
    ).model_dump(mode="json")


@mcp.tool()
async def approve_ai_proposal(
    proposal_id: str,
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Mutating metadata only: approve an AI proposal record without changing compliance truth.

    Args:
        proposal_id: Proposal id returned by propose_field_mapping.
        db_path: SQLite database path.

    Returns:
        Approved proposal metadata and provenance.
    """
    context = _mcp_context()
    return (
        AIProposalService(LocalRepository(db_path))
        .approve(context, proposal_id)
        .model_dump(mode="json")
    )


@mcp.tool()
async def collect_security_evidence(
    period: str = "current",
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Collect a readiness-only security/SOC2 evidence packet for auditor review."""
    context = _mcp_context(track=profile)
    return (
        SecurityEvidenceService(LocalRepository(db_path))
        .collect_packet(context, period=period)
        .model_dump(mode="json")
    )


@mcp.tool()
async def collect_governance_packet(
    lane: str = "workforce",
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Collect a readiness-only AI, HR-boundary, and school governance packet."""
    context = _mcp_context(track=profile)
    return (
        GovernancePacketService(LocalRepository(db_path))
        .collect_packet(context, lane=lane)
        .model_dump(mode="json")
    )


@mcp.tool()
async def create_privacy_request(
    subject_id: str,
    request_type: str,
    region: str | None = None,
    notes: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Create a privacy/data-subject request case.

    Args:
        subject_id: Subject/user identifier.
        request_type: access, export, correction, deletion, restriction, or objection.
        region: Optional jurisdiction label.
        notes: Optional internal notes.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        Privacy request metadata.
    """
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .create_request(
            context,
            subject_id=subject_id,
            request_type=request_type,
            region=region,
            notes=notes,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
async def export_privacy_subject(
    request_id: str,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Export subject data for a scoped privacy request."""
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .export_subject(context, request_id)
        .model_dump(mode="json")
    )


@mcp.tool()
async def approve_privacy_request(
    request_id: str,
    approval_note: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Record controller approval before exporting or deleting subject data."""
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .approve_request(context, request_id, approval_note=approval_note)
        .model_dump(mode="json")
    )


@mcp.tool()
async def delete_privacy_subject(
    request_id: str,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Delete subject data unless blocked by an active legal hold."""
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .delete_subject(context, request_id)
        .model_dump(mode="json")
    )


@mcp.tool()
async def create_legal_hold(
    subject_id: str | None,
    scope: str,
    reason: str,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Create an active legal hold that blocks deletion workflows."""
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .create_legal_hold(context, subject_id=subject_id, scope=scope, reason=reason)
        .model_dump(mode="json")
    )


@mcp.tool()
async def release_legal_hold(
    hold_id: str,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Release a legal hold."""
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .release_legal_hold(context, hold_id)
        .model_dump(mode="json")
    )


@mcp.tool()
async def configure_privacy_retention(
    raw_import_days: int,
    evidence_days: int,
    action_log_days: int,
    ai_proposal_days: int,
    privacy_request_days: int = 365,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Configure tenant retention settings for privacy program evidence."""
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .configure_retention_policy(
            context,
            raw_import_days=raw_import_days,
            evidence_days=evidence_days,
            action_log_days=action_log_days,
            ai_proposal_days=ai_proposal_days,
            privacy_request_days=privacy_request_days,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
async def run_privacy_retention(
    dry_run: bool = True,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Run retention cleanup for closed privacy program artifacts."""
    context = _mcp_context(track=profile)
    return (
        PrivacyProgramService(LocalRepository(db_path))
        .run_retention_cleanup(context, dry_run=dry_run)
        .model_dump(mode="json")
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
