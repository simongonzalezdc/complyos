"""MCP server exposing ComplyOS tools to AI agents."""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP

from complyos.config import ComplyOSConfig, resolve_env_placeholder
from complyos.connectors.base import LMSConnector
from complyos.connectors.blackboard import BlackboardConnector
from complyos.connectors.brightspace import BrightspaceConnector
from complyos.connectors.canvas import CanvasConnector
from complyos.connectors.cornerstone import CornerstoneConnector
from complyos.connectors.csv_file import CSVConnector
from complyos.connectors.mock import MockConnector
from complyos.connectors.moodle import MoodleConnector
from complyos.connectors.successfactors import SuccessFactorsConnector
from complyos.connectors.workday import WorkdayConnector
from complyos.core.audit_views import shape_gaps, shape_remediation, shape_report
from complyos.core.auditor import ComplianceAuditor
from complyos.core.repository import LocalRepository
from complyos.models.domain import AssignmentRule
from complyos.notification.sender import NotificationSender, build_notifier_from_env
from complyos.services.ai_proposals import AIProposalService
from complyos.services.attestations import AttestationService
from complyos.services.audit import AuditService
from complyos.services.connector_registry import ConnectorRegistry
from complyos.services.context import (
    PERM_EVIDENCE_EXPORT,
    PERM_NOTIFICATIONS_MANAGE,
    ROLE_PERMISSIONS,
    ActorContext,
    default_local_context,
    require_permission,
)
from complyos.services.evidence import EvidenceService
from complyos.services.governance import GovernancePacketService
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.intake import IntakeService
from complyos.services.policy_rules import PolicyRuleService
from complyos.services.privacy import PrivacyProgramService
from complyos.services.readiness import ReadinessService
from complyos.services.remediation import RemediationService
from complyos.services.rosters import RostersService
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


def _mcp_context(
    *, track: str = "workforce", tenant_id: str | None = None
) -> ActorContext:
    """Build the actor context for an MCP call, defaulting to least privilege.

    Routing every MCP tool through one context (instead of self-assigning
    privacy_admin/owner inline) enforces the "AI is proposal-only" guardrail at
    the surface boundary: privileged services fail closed unless the operator
    opts up with COMPLYOS_MCP_ROLE.

    Tenant scope: an operator deploying the MCP for one specific tenant should
    set ``COMPLYOS_MCP_TENANT_ID`` so the agent cannot be asked to operate on
    a different tenant via per-tool arguments. When unset, the default
    ``local-default`` tenant is used (single-tenant runtime, frozen default §3).
    """
    role = os.getenv("COMPLYOS_MCP_ROLE", DEFAULT_MCP_ROLE)
    if role not in ROLE_PERMISSIONS:
        raise ValueError(f"unknown COMPLYOS_MCP_ROLE: {role!r}")
    env_tenant = os.getenv("COMPLYOS_MCP_TENANT_ID")
    if tenant_id is not None and env_tenant and tenant_id != env_tenant:
        raise ValueError(
            "tenant_id argument conflicts with COMPLYOS_MCP_TENANT_ID; "
            f"got {tenant_id!r} but MCP is pinned to {env_tenant!r}"
        )
    effective_tenant = env_tenant or tenant_id or "local-default"
    return default_local_context(
        surface="mcp", track=track, role=role, tenant_id=effective_tenant
    )


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


def _canvas_from_config(config: ComplyOSConfig) -> CanvasConnector:
    connector_config = config.connector.get("canvas", {})
    return CanvasConnector(
        base_url=resolve_env_placeholder(connector_config.get("base_url")),
        api_token=resolve_env_placeholder(connector_config.get("api_token")),
        course_id=resolve_env_placeholder(connector_config.get("course_id")),
        account_id=resolve_env_placeholder(connector_config.get("account_id")),
    )


def _brightspace_from_config(config: ComplyOSConfig) -> BrightspaceConnector:
    connector_config = config.connector.get("brightspace", {})
    return BrightspaceConnector(
        base_url=resolve_env_placeholder(connector_config.get("base_url")),
        client_id=resolve_env_placeholder(connector_config.get("client_id")),
        client_secret=resolve_env_placeholder(connector_config.get("client_secret")),
        token_url=resolve_env_placeholder(connector_config.get("token_url")),
        org_unit_id=resolve_env_placeholder(connector_config.get("org_unit_id")),
    )


def _moodle_from_config(config: ComplyOSConfig) -> MoodleConnector:
    connector_config = config.connector.get("moodle", {})
    return MoodleConnector(
        base_url=resolve_env_placeholder(connector_config.get("base_url")),
        token=resolve_env_placeholder(connector_config.get("token")),
        course_id=resolve_env_placeholder(connector_config.get("course_id")),
    )


def _blackboard_from_config(config: ComplyOSConfig) -> BlackboardConnector:
    connector_config = config.connector.get("blackboard", {})
    return BlackboardConnector(
        base_url=resolve_env_placeholder(connector_config.get("base_url")),
        client_id=resolve_env_placeholder(connector_config.get("client_id")),
        client_secret=resolve_env_placeholder(connector_config.get("client_secret")),
        course_id=resolve_env_placeholder(connector_config.get("course_id")),
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
    if connector_type == "canvas":
        return _canvas_from_config(config)
    if connector_type == "brightspace":
        return _brightspace_from_config(config)
    if connector_type == "moodle":
        return _moodle_from_config(config)
    if connector_type == "blackboard":
        return _blackboard_from_config(config)
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
async def sync(db_path: str = "complyos.db") -> dict[str, Any]:
    """Mutating: pull LMS data into the local SQLite cache.

    Mirrors the CLI ``sync`` command and ``POST /api/v1/sync``. This clears and
    re-populates the local cache, so it is gated at audit:run. The default
    proposal-only MCP role (agent_service_account) holds audit:run; an unprivileged
    role is denied at the service boundary.

    Args:
        db_path: SQLite database path.

    Returns:
        Connector name and the count of synced users, courses, enrollments,
        and learning records.
    """
    result = await AuditService(_get_connector(), LocalRepository(db_path)).sync(_mcp_context())
    return dict(result)


@mcp.tool()
async def list_connectors(profile: str | None = None) -> dict[str, Any]:
    """Read-only: list the connector capability matrix.

    Mirrors the CLI ``connectors`` command and ``GET /api/v1/connectors``. Does
    not connect to or mutate any LMS; it reports configured connector
    capabilities only.

    Args:
        profile: Optional filter (all, workforce, or campus).

    Returns:
        The connector capability matrix.
    """
    # ConnectorRegistry.list owns the connectors:read check.
    return {"connectors": ConnectorRegistry(_get_connector()).list(_mcp_context(), profile=profile)}


@mcp.tool()
async def check_connector_health() -> dict[str, Any]:
    """Read-only: check the health of the LMS connector.

    Returns:
        Connector status, authentication state, and any errors.
    """
    # ConnectorRegistry.health owns the connectors:read check.
    return await ConnectorRegistry(_get_connector()).health(_mcp_context())


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
    rule = AssignmentRule(
        name=name,
        target_criteria=target_criteria,
        course_ids=course_ids,
        deadline_days_from_trigger=deadline_days,
    )
    # PolicyRuleService.validate owns the rules:preview check.
    return PolicyRuleService(LocalRepository()).validate(_mcp_context(), rule)


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
    rule = AssignmentRule(
        name=name,
        target_criteria=target_criteria,
        course_ids=course_ids,
        deadline_days_from_trigger=deadline_days,
    )
    # PolicyRuleService.preview owns the rules:preview check.
    return PolicyRuleService(LocalRepository()).preview(_mcp_context(), rule)


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
    # Route through EvidenceService.export_report so the evidence:export choke-point
    # gates this PII export. The default proposal-only MCP role lacks evidence:export
    # and is therefore denied; raise COMPLYOS_MCP_ROLE to a role that holds it.
    return await EvidenceService(_get_connector()).export_report(
        _mcp_context(),
        output_path=output_path,
        department=department,
        region=region,
    )


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
    # A dashboard is a PII-bearing report export, so it shares the report choke-point's
    # evidence:export requirement (not audit:read). The default proposal-only MCP role
    # is therefore denied; raise COMPLYOS_MCP_ROLE to a role that holds evidence:export.
    require_permission(_mcp_context(), PERM_EVIDENCE_EXPORT)
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
    """Mutating side effect: send a custom external email notification.

    Gated at notifications:manage. The default proposal-only MCP role
    (agent_service_account) lacks notifications:manage and is therefore DENIED,
    so a connected agent cannot send arbitrary external email; raise
    COMPLYOS_MCP_ROLE to a role that holds notifications:manage to allow it.

    Args:
        to_address: Recipient email address
        subject: Email subject line
        body: Plain-text email body

    Returns:
        Dict with 'sent' boolean and optional 'error' string.
    """
    # Fail closed before resolving SMTP credentials or sending any email.
    require_permission(_mcp_context(), PERM_NOTIFICATIONS_MANAGE)
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
    context = _mcp_context(tenant_id=tenant_id)
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


@mcp.tool()
async def list_attestations(
    user_id: str | None = None,
    requirement_id: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """List recorded AI-use-policy / AI-literacy attestations (read-only).

    Read-only: the default proposal-only agent role may list attestations so it
    can report which learners are un-attested, but it cannot record one (see
    record_attestation).

    Args:
        user_id: Optional learner filter.
        requirement_id: Optional requirement (learning item) filter.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The tenant's attestation records.
    """
    context = _mcp_context(track=profile)
    records = AttestationService(LocalRepository(db_path)).list_attestations(
        context, user_id=user_id, requirement_id=requirement_id
    )
    return {"items": [record.model_dump(mode="json") for record in records]}


@mcp.tool()
async def record_attestation(
    user_id: str,
    requirement_id: str,
    policy_version: str,
    expires_at: str | None = None,
    on_behalf: bool = False,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Mutating: record that a learner attested to a named AI-use policy version.

    An attestation is human-recorded evidence that a *person* read and accepted a
    policy. The default proposal-only MCP role lacks ``attestation:record`` and is
    therefore denied — AI can never mark a learner attested. Raise
    COMPLYOS_MCP_ROLE to a human-operated role (e.g. compliance_manager) only when
    a human is genuinely recording the attestation through the agent surface.

    Args:
        user_id: Learner who attested.
        requirement_id: Attestation requirement (learning item) id.
        policy_version: The named policy version the learner accepted.
        expires_at: Optional ISO date for annual re-attestation.
        on_behalf: True when an admin records on the learner's behalf.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The recorded attestation, its learning-record id, and its evidence id.
    """
    from datetime import date as _date

    context = _mcp_context(track=profile)
    parsed_expiry = _date.fromisoformat(expires_at) if expires_at else None
    return (
        AttestationService(LocalRepository(db_path))
        .record(
            context,
            user_id=user_id,
            requirement_id=requirement_id,
            policy_version=policy_version,
            expires_at=parsed_expiry,
            on_behalf=on_behalf,
        )
        .model_dump(mode="json")
    )


@mcp.tool()
async def submit_intake(
    title: str,
    requester: str,
    audience: str | None = None,
    priority: str | None = None,
    business_context: str | None = None,
    constraints: str | None = None,
    requested_by_date: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Proposal-only: capture a training request (DRAFT) and draft its packet.

    The default proposal-only agent role MAY do this (it holds ``intake:submit``).
    Submitting captures the request and drafts a proposal-only packet that flags
    missing info and SUGGESTS a priority + routing. It never confirms scope —
    that is a separate human step (see confirm_intake_scope), so an agent can
    triage requests but can never agree to do the work.

    Args:
        title: Short title of what training is requested.
        requester: Who is asking (name or id).
        audience: Who needs the training.
        priority: Optional low|medium|high|urgent (a human may override).
        business_context: Why this is needed / business driver.
        constraints: Timing, budget, compliance, or delivery constraints.
        requested_by_date: Optional ISO date (YYYY-MM-DD).
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The captured request and its proposal-only draft packet.
    """
    from datetime import date as _date

    context = _mcp_context(track=profile)
    parsed_by = _date.fromisoformat(requested_by_date) if requested_by_date else None
    service = IntakeService(LocalRepository(db_path))
    request = service.create_request(
        context,
        requester=requester,
        title=title,
        audience=audience,
        priority=priority,
        business_context=business_context,
        constraints=constraints,
        requested_by_date=parsed_by,
    )
    packet = service.draft_packet(context, request_id=request.id)
    return {
        "request": request.model_dump(mode="json"),
        "packet": packet.model_dump(mode="json"),
    }


@mcp.tool()
async def list_intake(
    status: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Read-only: list the tenant's training intake requests.

    The default proposal-only agent role may list intake requests (it holds
    ``intake:submit``) so it can triage and report the queue.

    Args:
        status: Optional filter: draft | confirmed | withdrawn.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The tenant's intake requests.
    """
    context = _mcp_context(track=profile)
    requests = IntakeService(LocalRepository(db_path)).list_requests(context, status=status)
    return {"items": [req.model_dump(mode="json") for req in requests]}


@mcp.tool()
async def confirm_intake_scope(
    request_id: str,
    note: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Mutating: confirm scope for an intake request (DRAFT -> CONFIRMED).

    This is the human guardrail. The default proposal-only MCP role lacks
    ``intake:confirm`` and is therefore denied — an AI/agent can never confirm
    scope. Raise COMPLYOS_MCP_ROLE to a human-operated role (e.g.
    compliance_manager) only when a human is genuinely confirming scope through
    the agent surface.

    Args:
        request_id: Intake request id to confirm scope for.
        note: Optional confirmation note.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The confirmed request with its human approver stamped.
    """
    context = _mcp_context(track=profile)
    return (
        IntakeService(LocalRepository(db_path))
        .confirm_scope(context, request_id=request_id, note=note)
        .model_dump(mode="json")
    )


@mcp.tool()
async def request_roster_snapshot(
    label: str,
    csv_text: str,
    source_system: str = "csv",
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Proposal-only: preview a source export into quarantine and draft a roster view.

    The default proposal-only agent role MAY do this (it holds ``rosters:read``).
    The export is routed through the import preview, which QUARANTINES the batch —
    nothing mutates the normalized truth. A proposal-only roster view (learners x
    learning-items, normalized status) is returned alongside the captured
    snapshot. Promotion is a separate human step (see approve_roster_snapshot),
    so an agent can preview and present but never let an import mutate truth.

    Args:
        label: Short label for this roster snapshot.
        csv_text: The source CSV export text.
        source_system: Source system label.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The captured snapshot and its proposal-only roster view.
    """
    context = _mcp_context(track=profile)
    service = RostersService(LocalRepository(db_path))
    snapshot = service.request_snapshot(
        context, label=label, csv_text=csv_text, source_system=source_system
    )
    packet = service.draft_packet(context, snapshot_id=snapshot.id)
    return {
        "snapshot": snapshot.model_dump(mode="json"),
        "packet": packet.model_dump(mode="json"),
    }


@mcp.tool()
async def list_rosters(
    status: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Read-only: list the tenant's roster snapshots.

    The default proposal-only agent role may list roster snapshots (it holds
    ``rosters:read``) so it can triage and report the queue.

    Args:
        status: Optional filter: draft | approved | withdrawn.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The tenant's roster snapshots.
    """
    context = _mcp_context(track=profile)
    snapshots = RostersService(LocalRepository(db_path)).list_snapshots(context, status=status)
    return {"items": [snap.model_dump(mode="json") for snap in snapshots]}


@mcp.tool()
async def approve_roster_snapshot(
    snapshot_id: str,
    note: str | None = None,
    profile: str = "workforce",
    db_path: str = "complyos.db",
) -> dict[str, Any]:
    """Mutating: approve a roster snapshot and promote its quarantined import.

    This is the quarantine guardrail. The default proposal-only MCP role lacks
    ``rosters:approve`` and is therefore denied — an AI/agent can never let a
    previewed import mutate normalized truth. Raise COMPLYOS_MCP_ROLE to a
    human-operated role (e.g. compliance_manager) only when a human is genuinely
    approving the import through the agent surface.

    Args:
        snapshot_id: Roster snapshot id to approve and import.
        note: Optional approval note.
        profile: workforce or campus.
        db_path: SQLite database path.

    Returns:
        The approved snapshot with its human approver stamped.
    """
    context = _mcp_context(track=profile)
    return (
        RostersService(LocalRepository(db_path))
        .approve_snapshot(context, snapshot_id=snapshot_id, note=note)
        .model_dump(mode="json")
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
