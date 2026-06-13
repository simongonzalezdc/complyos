"""CLI entry point for ComplyOS."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated, Any

import typer
import yaml
from rich.console import Console
from rich.table import Table

from complyos.api.mcp_server import _get_connector
from complyos.config import ComplyOSConfig
from complyos.core.audit_views import shape_gaps, shape_report
from complyos.core.release import build_deployment_checklist
from complyos.core.repository import LocalRepository
from complyos.core.time import utc_now
from complyos.microlearning import MicrolearningAdapter
from complyos.models.domain import AssignmentRule
from complyos.notification.outbox import EmailEventSender, WebhookEventSender
from complyos.notification.sender import NotificationSender, build_notifier_from_env
from complyos.notification.webhooks import WebhookNotifier
from complyos.regwatch import RegWatchAdapter
from complyos.services.ai_proposals import AIProposalService
from complyos.services.audit import AuditService
from complyos.services.connector_registry import ConnectorRegistry
from complyos.services.context import (
    ROLE_PERMISSIONS,
    ActorContext,
    default_local_context,
)
from complyos.services.evidence import EvidenceService
from complyos.services.governance import GovernancePacketService
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.notifications import NotificationOutboxService
from complyos.services.policy_rules import PolicyRuleService
from complyos.services.privacy import PrivacyProgramService
from complyos.services.readiness import ReadinessService
from complyos.services.remediation import RemediationService
from complyos.services.role_admin import RoleAdminService
from complyos.services.security_evidence import SecurityEvidenceService
from complyos.services.source_intel import SourceIntelService
from complyos.source_intel import (
    ECFRClient,
    FederalRegisterClient,
    SourceDefinition,
    SourceFetchReport,
    SourceIntelEngine,
    SourceMonitor,
    SourceReviewStore,
    SourceSnapshot,
    SourceType,
    free_public_source_definitions,
)

app = typer.Typer(name="complyos", help="L&D Compliance & Learning Operations")
import_app = typer.Typer(name="import", help="Preview, decide, and promote import batches")
evidence_app = typer.Typer(name="evidence", help="Inspect evidence ledger entries")
ai_app = typer.Typer(name="ai", help="Proposal-only AI assistance")
source_intel_app = typer.Typer(
    name="source-intel",
    help="No-paid source monitoring and review queue",
)
admin_app = typer.Typer(name="admin", help="Administrative inspection commands")
admin_role_bindings_app = typer.Typer(
    name="role-bindings",
    help="Manage tenant-scoped role bindings",
)
governance_app = typer.Typer(name="governance", help="AI, HR, and school governance packets")
privacy_app = typer.Typer(name="privacy", help="Privacy requests, retention, and legal holds")
privacy_retention_app = typer.Typer(name="retention", help="Configure retention policies")
security_app = typer.Typer(name="security", help="Security evidence and assurance readiness")
notifications_app = typer.Typer(name="notifications", help="Drain notification outbox deliveries")
console = Console()


def _local_cli_context(*, track: str = "workforce", role: str = "owner"):
    return default_local_context(surface="cli", track=track, role=role)


def _print_json(data: object) -> None:
    console.print(json.dumps(data, indent=2, default=str), soft_wrap=True)


def _get_notifier() -> NotificationSender | None:
    """Build a NotificationSender from environment or return None."""
    return build_notifier_from_env()


def _get_webhook_notifier() -> WebhookNotifier | None:
    """Build a webhook notifier from environment or return None."""
    slack_url = os.getenv("COMPLYOS_SLACK_WEBHOOK_URL")
    teams_url = os.getenv("COMPLYOS_TEAMS_WEBHOOK_URL")
    if not slack_url and not teams_url:
        return None
    return WebhookNotifier(slack_webhook_url=slack_url, teams_webhook_url=teams_url)


def _get_outbox_sender() -> WebhookEventSender:
    """Build a generic event sender without exposing webhook URLs in logs."""
    channel_urls = {
        "slack": os.getenv("COMPLYOS_SLACK_WEBHOOK_URL") or "",
        "teams": os.getenv("COMPLYOS_TEAMS_WEBHOOK_URL") or "",
        "webhook": os.getenv("COMPLYOS_WEBHOOK_URL") or "",
    }
    return WebhookEventSender(
        channel_urls=channel_urls,
        signing_secret=os.getenv("COMPLYOS_WEBHOOK_SECRET"),
    )


def _get_email_outbox_sender() -> EmailEventSender:
    """Build an SMTP-backed event sender with env-configured default recipients."""
    recipients = [
        item.strip()
        for item in os.getenv("COMPLYOS_NOTIFICATION_EMAIL_TO", "").split(",")
        if item.strip()
    ]
    return EmailEventSender(
        notification_sender=_get_notifier() or NotificationSender(),
        default_recipients=recipients,
    )


@app.command()
def audit(
    department: str | None = typer.Option(None, "--department", "-d", help="Filter by department"),
    region: str | None = typer.Option(None, "--region", "-r", help="Filter by region"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Audit compliance training gaps."""

    async def _audit():
        gaps, ledger = await AuditService(_get_connector()).run_audit(
            _local_cli_context(), department=department, region=region
        )
        return shape_gaps(gaps, ledger)

    result = asyncio.run(_audit())

    if json_output:
        console.print(json.dumps(result, indent=2, default=str))
        return

    console.print(f"[bold]Gaps found:[/bold] {result['gaps_found']}")
    console.print(f"[bold]Users affected:[/bold] {result['users_affected']}")
    console.print(f"[bold]Evidence hash:[/bold] {result['evidence_hash']}")

    if result["gaps"]:
        table = Table(title="Compliance Gaps")
        table.add_column("User")
        table.add_column("Department")
        table.add_column("Missing Courses")
        table.add_column("Severity")
        table.add_column("Days Overdue")

        for gap in result["gaps"]:
            table.add_row(
                f"{gap['user']['name']} ({gap['user']['email']})",
                gap["user"]["department"],
                ", ".join(gap["missing_courses"]),
                gap["severity"],
                str(gap["days_overdue"]) if gap["days_overdue"] else "—",
            )
        console.print(table)


@app.command()
def report(
    department: str | None = typer.Option(None, "--department", "-d"),
    region: str | None = typer.Option(None, "--region", "-r"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Generate a structured audit report."""

    async def _report():
        report_model = await AuditService(_get_connector()).generate_report(
            _local_cli_context(), department=department, region=region
        )
        return shape_report(report_model)

    result = asyncio.run(_report())

    if json_output:
        console.print(json.dumps(result, indent=2, default=str))
        return

    console.print(f"[bold]Generated:[/bold] {result['generated_at']}")
    console.print(f"[bold]Scope:[/bold] {result['scope']}")
    console.print(f"[bold]Gaps found:[/bold] {result['gaps_found']}")
    console.print(f"[bold]Evidence hash:[/bold] {result['evidence_hash']}")

    if result["gaps_by_severity"]:
        table = Table(title="Gaps by Severity")
        table.add_column("Severity")
        table.add_column("Count")
        for sev, count in result["gaps_by_severity"].items():
            table.add_row(sev, str(count))
        console.print(table)

    if result["top_missing_courses"]:
        table = Table(title="Top Missing Courses")
        table.add_column("Course")
        table.add_column("Missing Count")
        for course, count in result["top_missing_courses"]:
            table.add_row(course, str(count))
        console.print(table)


@app.command()
def status(
    user_id: str = typer.Argument(..., help="User ID to check"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Get compliance status for a single user."""

    async def _status():
        return await AuditService(_get_connector()).get_status(
            _local_cli_context(), user_id=user_id
        )

    result = asyncio.run(_status())

    if json_output:
        console.print(json.dumps(result, indent=2, default=str))
        return

    if "error" in result:
        console.print(f"[red]Error:[/red] {result['error']}")
        raise typer.Exit(1)

    user = result["user"]
    summary = result["summary"]

    console.print(f"[bold]{user['first_name']} {user['last_name']}[/bold] ({user['email']})")
    console.print(f"Department: {user['department']} | Region: {user['region']}")
    console.print(
        f"Compliance: {summary['completed']}/{summary['total_mandatory']} "
        f"({summary['compliance_rate'] * 100:.0f}%)"
    )

    if result["courses"]:
        table = Table(title="Course Status")
        table.add_column("Course")
        table.add_column("Status")
        table.add_column("Compliant")
        for cs in result["courses"]:
            course = cs["course"]
            compliant = "[green]Yes[/green]" if cs["compliant"] else "[red]No[/red]"
            enrollment = cs["enrollment"]
            status_text = enrollment["status"] if enrollment else "Not Assigned"
            table.add_row(course["title"], status_text, compliant)
        console.print(table)


@app.command()
def digest(
    department: str | None = typer.Option(None, "--department", "-d"),
    region: str | None = typer.Option(None, "--region", "-r"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    json_output: bool = typer.Option(False, "--json"),
):
    """Show what changed since the last audit: new gaps, resolved gaps, trend."""

    async def _digest():
        digest_model = await AuditService(_get_connector(), LocalRepository(db_path)).get_digest(
            _local_cli_context(), department=department, region=region
        )
        return digest_model.model_dump(mode="json")

    result = asyncio.run(_digest())

    if json_output:
        console.print(json.dumps(result, indent=2, default=str))
        return

    trend_colors = {"improving": "green", "worsening": "red", "flat": "yellow", "baseline": "cyan"}
    trend_color = trend_colors.get(result["trend"], "white")

    console.print(f"[bold]Scope:[/bold] {result['scope']}")
    console.print(f"[bold]Current gaps:[/bold] {result['current_gaps']}")
    if result["previous_gaps"] is not None:
        console.print(
            f"[bold]Previous gaps:[/bold] {result['previous_gaps']} "
            f"(as of {result['previous_generated_at']})"
        )
    console.print(f"[bold]Trend:[/bold] [{trend_color}]{result['trend']}[/{trend_color}]")
    console.print(f"[bold]Evidence hash:[/bold] {result['evidence_hash']}")

    if result["trend"] == "baseline":
        console.print(
            "[cyan]First digest for this scope — baseline recorded. "
            "Run again after the next sync to see changes.[/cyan]"
        )

    if result["new_gaps"]:
        table = Table(title=f"New Gaps ({len(result['new_gaps'])})")
        table.add_column("User")
        table.add_column("Department")
        table.add_column("Course")
        table.add_column("Severity")
        for entry in result["new_gaps"]:
            table.add_row(
                f"{entry['user_name']} ({entry['user_email']})",
                entry["department"],
                entry["course_title"],
                entry["severity"],
            )
        console.print(table)

    if result["resolved_gaps"]:
        table = Table(title=f"Resolved Gaps ({len(result['resolved_gaps'])})")
        table.add_column("User")
        table.add_column("Department")
        table.add_column("Course")
        for entry in result["resolved_gaps"]:
            table.add_row(
                f"{entry['user_name']} ({entry['user_email']})",
                entry["department"],
                entry["course_title"],
            )
        console.print(table)


@app.command()
def health():
    """Check LMS connector health."""
    result = asyncio.run(
        ConnectorRegistry(_get_connector()).health(_local_cli_context())
    )

    status_color = "green" if result["status"] == "healthy" else "red"
    console.print(f"[bold]Connector:[/bold] {result['connector']}")
    console.print(f"[bold]Authenticated:[/bold] {result['authenticated']}")
    console.print(f"[bold]Status:[/bold] [{status_color}]{result['status']}[/{status_color}]")

    if "error" in result:
        console.print(f"[red]Error:[/red] {result['error']}")


@app.command()
def init(
    profile: str = typer.Option("workforce", "--profile", help="Profile: workforce or campus"),
    output: str = typer.Option("complyos.yaml", "--output", help="Config file to write"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config file"),
):
    """Initialize a starter ComplyOS config file."""
    from complyos.profiles import get_profile, render_profile_config

    try:
        definition = get_profile(profile)
        config = render_profile_config(profile)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    path = Path(output)
    if path.exists() and not force:
        console.print(
            f"[red]Config already exists at {path}. Use --force to overwrite.[/red]",
            soft_wrap=True,
        )
        raise typer.Exit(1)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(config)
    console.print(f"[green]Initialized {definition.display_name} config at {path}[/green]")


@app.command()
def connectors(
    profile: str = typer.Option("all", "--profile", help="Filter: all, workforce, or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Show the connector capability matrix."""
    try:
        items = ConnectorRegistry(_get_connector()).list(_local_cli_context(), profile=profile)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if json_output:
        console.print(json.dumps(items, indent=2))
        return

    table = Table(title="ComplyOS Connector Matrix")
    table.add_column("Name", no_wrap=True)
    table.add_column("Profile")
    table.add_column("Status")
    table.add_column("Auth")
    table.add_column("Records")
    table.add_column("Due Dates")
    table.add_column("Expiry")

    for item in items:
        table.add_row(
            str(item["name"]),
            str(item["profile"]),
            str(item["status"]),
            str(item["auth"]),
            "yes" if item["supports_learning_records"] else "no",
            "yes" if item["supports_due_dates"] else "no",
            "yes" if item["supports_expiry"] else "no",
        )
    console.print(table)


@app.command()
def sync(
    db_path: str | None = typer.Option(None, "--db", help="Path to SQLite database"),
):
    """Sync LMS data into local SQLite cache."""
    resolved_db_path = db_path or ComplyOSConfig.load().database_path()
    connector = _get_connector()
    repo = LocalRepository(resolved_db_path)

    async def _sync():
        healthy = await connector.authenticate()
        if not healthy:
            console.print("[red]Connector authentication failed[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]Syncing from {connector.name}...[/bold]")

        users = await connector.get_users()
        courses = await connector.get_courses()
        enrollments = await connector.get_enrollments()
        learning_records = await connector.get_learning_records()

        repo.clear_all()
        repo.sync_users(users)
        repo.sync_courses(courses)
        repo.sync_enrollments(enrollments)
        repo.sync_learning_records(learning_records)

        return len(users), len(courses), len(enrollments), len(learning_records)

    user_count, course_count, enrollment_count, learning_record_count = asyncio.run(_sync())
    console.print(
        f"[green]Synced {user_count} users, {course_count} courses, "
        f"{enrollment_count} enrollments, {learning_record_count} learning records[/green]"
    )


def _audit_schedule_notification_events(
    *,
    notification_service: NotificationOutboxService,
    context: ActorContext,
    result: Any,
    channels: list[str],
) -> list[dict[str, Any]]:
    events = [
        notification_service.enqueue_event(
            context,
            event_type="audit.completed",
            object_type="audit_snapshot",
            object_id=result.snapshot_id,
            payload={
                "job_name": result.job_name,
                "scope": result.scope,
                "gaps_found": result.gaps_found,
                "gaps_by_severity": result.gaps_by_severity,
                "evidence_hash": result.evidence_hash,
                "email_subject": "ComplyOS scheduled audit completed",
                "summary": (
                    f"Scheduled audit {result.job_name} completed with {result.gaps_found} gaps."
                ),
            },
            channels=channels,
        )
    ]
    high_risk_count = int(result.gaps_by_severity.get("critical", 0)) + int(
        result.gaps_by_severity.get("high", 0)
    )
    if high_risk_count:
        events.append(
            notification_service.enqueue_event(
                context,
                event_type="audit.high_risk_gaps_found",
                object_type="audit_snapshot",
                object_id=result.snapshot_id,
                payload={
                    "job_name": result.job_name,
                    "scope": result.scope,
                    "high_risk_count": high_risk_count,
                    "gaps_by_severity": result.gaps_by_severity,
                    "email_subject": "ComplyOS high-risk audit gaps found",
                    "summary": (
                        f"Scheduled audit {result.job_name} found "
                        f"{high_risk_count} high/critical gaps."
                    ),
                },
                channels=channels,
            )
        )
    return events


@app.command("run-schedule")
def run_schedule(
    config_path: str = typer.Option(
        "complyos.yaml",
        "--config",
        help="Config file with schedule.jobs",
    ),
    db_path: str | None = typer.Option(None, "--db", help="Path to SQLite database"),
    force: bool = typer.Option(False, "--force", help="Run jobs even when last_run_at is not due"),
    enqueue_notifications: bool = typer.Option(
        True,
        "--enqueue-notifications/--no-enqueue-notifications",
        help="Queue audit notification events without sending network calls",
    ),
    notify_channel: Annotated[
        list[str] | None,
        typer.Option("--notify-channel", help="Notification channel to enqueue"),
    ] = None,
):
    """Run due scheduled audit jobs once."""
    from complyos.api.mcp_server import _get_auditor
    from complyos.core.scheduler import load_scheduled_jobs, run_scheduled_audit_once

    path = Path(config_path)
    if not path.exists():
        console.print(f"[red]Config not found: {path}[/red]")
        raise typer.Exit(1)

    config_data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    jobs = load_scheduled_jobs(config_data)
    if not jobs:
        console.print("[yellow]No scheduled audit jobs configured[/yellow]")
        return

    repo = LocalRepository(db_path or ComplyOSConfig.load(config_path).database_path())
    auditor = _get_auditor()
    notifier = _get_webhook_notifier()
    context = _local_cli_context(role="compliance_manager")
    notification_service = NotificationOutboxService(repo)
    channels = notify_channel or ["email", "slack", "teams"]

    async def _run():
        results = []
        for job in jobs:
            if force or job.is_due():
                results.append(
                    await run_scheduled_audit_once(
                        job,
                        auditor=auditor,
                        repository=repo,
                        notifier=notifier,
                    )
                )
        return results

    results = asyncio.run(_run())
    if not results:
        console.print("[yellow]No scheduled audit jobs were due[/yellow]")
        return

    if enqueue_notifications:
        for result in results:
            _audit_schedule_notification_events(
                notification_service=notification_service,
                context=context,
                result=result,
                channels=channels,
            )

    table = Table(title="Scheduled Audit Runs")
    table.add_column("Job")
    table.add_column("Scope")
    table.add_column("Gaps")
    table.add_column("Snapshot")
    for result in results:
        table.add_row(
            result.job_name,
            result.scope,
            str(result.gaps_found),
            result.snapshot_id,
        )
    console.print(table)


@app.command("release-check")
def release_check(
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Check whether the repository has operator-release artifacts."""
    from complyos.core.release import build_release_checklist

    checks = build_release_checklist(Path.cwd())
    ready = all(item["ok"] for item in checks)
    if json_output:
        console.print(json.dumps({"ready": ready, "checks": checks}, indent=2))
        if not ready:
            raise typer.Exit(1)
        return

    table = Table(title="Release Readiness")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Message")
    for item in checks:
        table.add_row(
            item["label"],
            "[green]ok[/green]" if item["ok"] else "[red]missing[/red]",
            item["message"],
        )
    console.print(table)
    if not ready:
        raise typer.Exit(1)


@app.command()
def mcp():
    """Run the MCP server."""
    from complyos.api.mcp_server import main

    main()


@app.command()
def validate_rule(
    rule_file: str = typer.Argument(..., help="Path to JSON rule definition"),
    db_path: str = typer.Option("complyos.db", "--db"),
):
    """Validate an assignment rule before deployment."""
    with open(rule_file) as f:
        data = json.load(f)

    rule = AssignmentRule(**data)
    result = PolicyRuleService(LocalRepository(db_path)).validate(_local_cli_context(), rule)

    if result["valid"]:
        console.print("[green]Rule is valid[/green]")
    else:
        console.print("[red]Rule has issues:[/red]")
        for issue in result["issues"]:
            console.print(f"  • {issue}")

    preview = result["preview"]
    console.print(f"Would affect {len(preview['users'])} users")


@app.command()
def preview_rule(
    rule_file: str = typer.Argument(..., help="Path to JSON rule definition"),
    db_path: str = typer.Option("complyos.db", "--db"),
):
    """Preview which users would be affected by a rule."""
    with open(rule_file) as f:
        data = json.load(f)

    rule = AssignmentRule(**data)
    result = PolicyRuleService(LocalRepository(db_path)).preview(_local_cli_context(), rule)

    console.print(f"[bold]Rule:[/bold] {result['rule_name']}")
    console.print(
        f"[bold]Affected users:[/bold] {len(result['users'])} "
        f"({result['total_missing_enrollments']} missing enrollments)"
    )

    if result["users"]:
        table = Table(title="Affected Users")
        table.add_column("User")
        table.add_column("Department")
        table.add_column("Missing Courses")
        for item in result["users"]:
            user = item["user"]
            table.add_row(
                f"{user.first_name} {user.last_name}",
                user.department,
                ", ".join(c.title for c in item["missing_courses"]),
            )
        console.print(table)


@app.command()
def remediate(
    department: str | None = typer.Option(None, "--department", "-d"),
    region: str | None = typer.Option(None, "--region", "-r"),
    auto_remind: bool = typer.Option(True, "--remind/--no-remind"),
    auto_enroll: bool = typer.Option(False, "--enroll/--no-enroll"),
    notify_manager: bool = typer.Option(False, "--notify-manager/--no-notify-manager"),
):
    """Audit and remediate compliance gaps."""

    # Remediation mutates state (reminders, enrollment, manager notifications), so
    # RemediationService.execute owns the remediation:execute check on the local
    # operator context rather than running unattributed.
    async def _remediate():
        return await RemediationService(_get_connector(), notifier=_get_notifier()).execute(
            _local_cli_context(),
            department=department,
            region=region,
            auto_remind=auto_remind,
            auto_enroll=auto_enroll,
            notify_manager=notify_manager,
        )

    gaps, actions, ledger = asyncio.run(_remediate())
    console.print(f"[bold]Gaps found:[/bold] {len(gaps)}")
    console.print(f"[bold]Actions taken:[/bold] {len(actions)}")
    console.print(f"[bold]Evidence hash:[/bold] {ledger.output_hash}")

    if actions:
        table = Table(title="Remediation Actions")
        table.add_column("Action")
        table.add_column("User")
        table.add_column("Course")
        table.add_column("Status")
        for action in actions:
            table.add_row(
                action.action_type,
                action.user_id,
                action.course_id,
                action.status,
            )
        console.print(table)


@app.command()
def export(
    output: str = typer.Argument("report.html", help="Output HTML file path"),
    department: str | None = typer.Option(None, "--department", "-d"),
    region: str | None = typer.Option(None, "--region", "-r"),
):
    """Export an audit report to HTML."""

    async def _export():
        return await EvidenceService(_get_connector()).export_report(
            _local_cli_context(),
            output_path=output,
            department=department,
            region=region,
        )

    result = asyncio.run(_export())
    console.print(f"[green]Report exported to {result['output_path']}[/green]")


@app.command()
def dashboard(
    output: str = typer.Argument("dashboard.html", help="Output HTML file path"),
    department: str | None = typer.Option(None, "--department", "-d"),
    region: str | None = typer.Option(None, "--region", "-r"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    open_browser: bool = typer.Option(False, "--open", help="Open in default browser"),
):
    """Generate a self-contained HTML compliance dashboard."""
    from complyos.api.mcp_server import _get_auditor
    from complyos.core.dashboard import generate_dashboard

    async def _build():
        auditor = _get_auditor()
        return await auditor.generate_report(department=department, region=region)

    report = asyncio.run(_build())
    history = LocalRepository(db_path).list_audit_snapshots(scope=report.scope)
    path = generate_dashboard(report, history=history, output_path=output)
    console.print(f"[green]Dashboard written to {path}[/green]")

    if open_browser:
        import os
        import webbrowser

        webbrowser.open(f"file://{os.path.abspath(path)}")


@app.command("serve-dashboard")
def serve_dashboard(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host"),
    port: int = typer.Option(8000, "--port", help="Bind port"),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Print bind address without starting server",
    ),
):
    """Serve the live compliance dashboard API."""
    if dry_run:
        console.print(f"[green]Dashboard dry run:[/green] would serve on {host}:{port}")
        return

    import uvicorn

    from complyos.api.mcp_server import _get_auditor
    from complyos.web.dashboard import create_dashboard_app

    uvicorn.run(create_dashboard_app(auditor=_get_auditor()), host=host, port=port)


@app.command()
def notify_test(
    to: str = typer.Argument(..., help="Recipient email address"),
):
    """Send a test notification to verify SMTP configuration."""
    notifier = _get_notifier()
    if notifier is None:
        console.print(
            "[yellow]SMTP not configured. Set COMPLYOS_SMTP_HOST, "
            "COMPLYOS_SMTP_USERNAME, and COMPLYOS_SMTP_PASSWORD.[/yellow]"
        )
        raise typer.Exit(1)

    async def _send():
        return await notifier.send_email(
            to_address=to,
            subject="ComplyOS Test Notification",
            body=(
                "Hi there,\n\n"
                "This is a test message from ComplyOS.\n"
                "Your SMTP configuration is working correctly.\n\n"
                "— ComplyOS"
            ),
        )

    result = asyncio.run(_send())
    if result["sent"]:
        console.print(f"[green]Test email sent to {to}[/green]")
    else:
        console.print(f"[red]Failed to send email: {result.get('error')}[/red]")
        raise typer.Exit(1)


@app.command()
def readiness(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Run readiness checks without claiming certification/compliance."""
    context = _local_cli_context(track=track)
    result = ReadinessService(LocalRepository(db_path)).check(context)
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return

    console.print("[yellow]Local CLI context:[/yellow] local-admin (readiness-only)")
    console.print(f"[bold]Posture:[/bold] {result.posture}")
    table = Table(title="Readiness Controls")
    table.add_column("Control")
    table.add_column("Area")
    table.add_column("Status")
    table.add_column("Artifact")
    for control in result.controls:
        table.add_row(control.title, control.area, control.status, control.artifact)
    console.print(table)


@import_app.command("preview")
def import_preview(
    path: str = typer.Argument(..., help="CSV file to preview"),
    source_system: str = typer.Option("csv", "--source-system", help="Source system name"),
    profile: str = typer.Option("workforce", "--profile", help="workforce or campus"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Preview and quarantine a CSV import; does not mutate active records."""
    context = _local_cli_context(track=profile)
    request = ImportPreviewRequest(source_system=source_system, profile=profile, path=path)
    result = ImportService(LocalRepository(db_path)).preview(context, request)
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return

    console.print("[yellow]Local CLI context:[/yellow] local-admin (import preview)")
    console.print(f"[bold]Batch:[/bold] {result.batch_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")
    console.print(f"[bold]Rows:[/bold] {result.total_rows}")
    console.print(f"[bold]Can promote:[/bold] {'yes' if result.can_promote else 'no'}")
    if result.issues:
        table = Table(title="Import Issues")
        table.add_column("Code")
        table.add_column("Severity")
        table.add_column("Row")
        table.add_column("Column")
        table.add_column("Message")
        for issue in result.issues:
            table.add_row(
                issue.code,
                issue.severity,
                str(issue.row_number or "—"),
                issue.column or "—",
                issue.message,
            )
        console.print(table)


@import_app.command("promote")
def import_promote(
    batch_id: str = typer.Argument(..., help="Import batch ID"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Promote a validated/quarantined import batch into active records."""
    context = _local_cli_context(track=track)
    result = ImportService(LocalRepository(db_path)).promote(context, batch_id)
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return

    console.print("[yellow]Local CLI context:[/yellow] local-admin (import promote)")
    console.print(f"[bold]Batch:[/bold] {result.batch_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")
    console.print(f"[bold]Promoted rows:[/bold] {result.promoted_rows}")
    console.print(f"[bold]Blocked rows:[/bold] {result.blocked_rows}")
    if result.evidence_id:
        console.print(f"[bold]Evidence id:[/bold] {result.evidence_id}")


@import_app.command("decide")
def import_decide(
    batch_id: str = typer.Argument(..., help="Import batch ID"),
    row_id: str = typer.Argument(..., help="Import row ID"),
    decision_type: str = typer.Option(
        ...,
        "--decision",
        help="accept, reject, map_field, merge_duplicate, ignore_row, require_manual_review",
    ),
    reason: str | None = typer.Option(None, "--reason", help="Decision reason"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Record an explicit row decision before promotion."""
    context = _local_cli_context(track=track)
    result = ImportService(LocalRepository(db_path)).decide(
        context,
        batch_id=batch_id,
        row_id=row_id,
        decision_type=decision_type,
        reason=reason,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return

    console.print("[yellow]Local CLI context:[/yellow] local-admin (import decision)")
    console.print(f"[bold]Batch:[/bold] {result.batch_id}")
    console.print(f"[bold]Row:[/bold] {result.row_id}")
    console.print(f"[bold]Decision:[/bold] {result.decision_type}")
    console.print(f"[bold]Row status:[/bold] {result.row_status}")


@evidence_app.command("list")
def evidence_list(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    tenant_id: str = typer.Option("local-default", "--tenant", help="Tenant ID"),
    limit: int = typer.Option(50, "--limit", help="Maximum rows"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List evidence ledger entries."""
    items = LocalRepository(db_path).list_evidence_ledger(tenant_id=tenant_id, limit=limit)
    if json_output:
        _print_json({"items": items})
        return

    table = Table(title="Evidence Ledger")
    table.add_column("Time")
    table.add_column("Type")
    table.add_column("Output hash")
    table.add_column("Summary")
    for item in items:
        table.add_row(
            str(item["timestamp"]),
            item["query_type"],
            item["output_hash"][:12],
            item["output_summary"],
        )
    console.print(table)


@ai_app.command("propose-mapping")
def ai_propose_mapping(
    headers: Annotated[list[str], typer.Argument(..., help="CSV headers to map")],
    target_schema: str = typer.Option("learning_records", "--target-schema"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Create a proposal-only field-mapping suggestion. No records mutate."""
    context = _local_cli_context(track=track)
    result = AIProposalService(LocalRepository(db_path)).propose_mapping(
        context,
        headers=headers,
        target_schema=target_schema,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return

    console.print(f"[bold]Proposal:[/bold] {result.proposal_id}")
    console.print("[yellow]Proposal-only:[/yellow] no compliance state was changed")
    for header, mapped in result.output["suggested_mappings"].items():
        console.print(f"  {header} -> {mapped or 'unmapped'}")


@ai_app.command("approve")
def ai_approve(
    proposal_id: str = typer.Argument(..., help="AI proposal ID"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Approve an AI proposal record; approval still does not mutate compliance truth."""
    context = _local_cli_context(track=track)
    result = AIProposalService(LocalRepository(db_path)).approve(context, proposal_id)
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[green]Approved proposal {result.proposal_id}[/green]")
    console.print("[yellow]No compliance records were changed by this approval.[/yellow]")


class _FixtureSourceClient:
    """No-network fixture client for local source-intelligence demos."""

    def fetch(self, source: SourceDefinition, *, query: str) -> SourceFetchReport:
        snapshot = SourceSnapshot.from_text(
            source_id=source.id,
            url=source.url,
            title="Fixture final rule and microlearning cue",
            text=(
                "A final rule says covered employers must train workers. "
                "Managers can use scenario practice, examples, and a checklist "
                f"for {query} follow-up."
            ),
            metadata={"fixture": True, "query": query},
        )
        return SourceFetchReport(source_id=source.id, snapshots=[snapshot], coverage_gaps=[])


def _fixture_source() -> SourceDefinition:
    return SourceDefinition(
        id="fixture-official-training-source",
        name="Fixture official training source",
        url="https://example.gov/fixture-training-rule",
        source_type=SourceType.OFFICIAL_REGULATOR,
        authority="official",
        jurisdictions=["US"],
        topics=["safety training", "manager feedback"],
        metadata={"cost": "free", "auth": "none", "fixture": True},
    )


def _run_fixture_source_monitor(query: str):
    source = _fixture_source()
    monitor = SourceMonitor(
        sources=[source],
        clients={source.id: _FixtureSourceClient()},
        engine=SourceIntelEngine(adapters=[RegWatchAdapter(), MicrolearningAdapter()]),
    )
    return monitor.run(query=query)


@source_intel_app.command("sources")
def source_intel_sources(
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List built-in no-paid source definitions and blocked parser gaps."""
    sources = list(free_public_source_definitions().values())
    payload = {"sources": [source.model_dump(mode="json") for source in sources]}
    if json_output:
        _print_json(payload)
        return

    table = Table(title="No-paid Source Intelligence Sources")
    table.add_column("Source")
    table.add_column("Jurisdiction")
    table.add_column("Cost")
    table.add_column("Auth")
    table.add_column("Status")
    for source in sources:
        table.add_row(
            source.name,
            ", ".join(source.jurisdictions),
            str(source.metadata.get("cost", "unknown")),
            str(source.metadata.get("auth", "unknown")),
            str(source.metadata.get("status", "unknown")),
        )
    console.print(table)


@source_intel_app.command("run-fixture")
def source_intel_run_fixture(
    store_path: str = typer.Option(
        "source-intel-reviews.jsonl",
        "--store",
        help="Local JSONL review queue path",
    ),
    db_path: str | None = typer.Option(None, "--db", help="Optional SQLite DB review queue"),
    query: str = typer.Option("training", "--query", help="Source-monitoring query label"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Run a no-network fixture through RegWatch and MicroLearn adapters."""
    run = _run_fixture_source_monitor(query)
    SourceReviewStore(store_path).save_many(run.proposals)
    db_receipt = None
    if db_path:
        context = _local_cli_context(role="compliance_manager")
        db_receipt = SourceIntelService(LocalRepository(db_path)).record_run(
            context,
            query=query,
            run=run,
        )
    payload = {
        "source_count": run.source_count,
        "snapshot_count": run.snapshot_count,
        "proposal_count": run.proposal_count,
        "proposal_ids": [proposal.id for proposal in run.proposals],
        "coverage_gaps": run.coverage_gaps,
        "store": store_path,
        "db_receipt": db_receipt,
    }
    if json_output:
        _print_json(payload)
        return

    console.print(f"[bold]Sources checked:[/bold] {run.source_count}")
    console.print(f"[bold]Snapshots:[/bold] {run.snapshot_count}")
    console.print(f"[bold]Proposals saved:[/bold] {run.proposal_count}")
    console.print(f"[bold]Store:[/bold] {store_path}")


@source_intel_app.command("run-public")
def source_intel_run_public(
    store_path: str = typer.Option(
        "source-intel-reviews.jsonl",
        "--store",
        help="Local JSONL review queue path",
    ),
    query: str = typer.Option("training", "--query", help="Search query for public sources"),
    source_filter: str | None = typer.Option(
        None,
        "--source",
        help="Comma-separated source IDs; defaults to implemented free clients",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show planned free calls only"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Run implemented free/public source clients; no paid accounts required."""
    all_sources = free_public_source_definitions()
    default_ids = ["federal-register", "ecfr-title-29"]
    source_ids = (
        [item.strip() for item in source_filter.split(",") if item.strip()]
        if source_filter
        else default_ids
    )
    missing = [source_id for source_id in source_ids if source_id not in all_sources]
    if missing:
        console.print(f"[red]Unknown source IDs:[/red] {', '.join(missing)}")
        raise typer.Exit(1)

    payload_base = {
        "dry_run": dry_run,
        "query": query,
        "source_ids": source_ids,
        "store": store_path,
    }
    if dry_run:
        if json_output:
            _print_json(payload_base)
            return
        console.print("[yellow]Dry run only:[/yellow] no network calls made")
        console.print(f"[bold]Query:[/bold] {query}")
        console.print(f"[bold]Sources:[/bold] {', '.join(source_ids)}")
        console.print(f"[bold]Store:[/bold] {store_path}")
        return

    selected_sources = [all_sources[source_id] for source_id in source_ids]
    clients: dict[str, Any] = {
        "federal-register": FederalRegisterClient(),
        "ecfr-title-29": ECFRClient(),
    }
    monitor = SourceMonitor(
        sources=selected_sources,
        clients=clients,
        engine=SourceIntelEngine(adapters=[RegWatchAdapter(), MicrolearningAdapter()]),
    )
    run = monitor.run(query=query)
    SourceReviewStore(store_path).save_many(run.proposals)
    payload = {
        **payload_base,
        "source_count": run.source_count,
        "snapshot_count": run.snapshot_count,
        "proposal_count": run.proposal_count,
        "proposal_ids": [proposal.id for proposal in run.proposals],
        "coverage_gaps": run.coverage_gaps,
    }
    if json_output:
        _print_json(payload)
        return

    console.print(f"[bold]Sources checked:[/bold] {run.source_count}")
    console.print(f"[bold]Snapshots:[/bold] {run.snapshot_count}")
    console.print(f"[bold]Proposals saved:[/bold] {run.proposal_count}")
    if run.coverage_gaps:
        for gap in run.coverage_gaps:
            console.print(f"[yellow]Coverage gap:[/yellow] {gap}")


@source_intel_app.command("run-upload")
def source_intel_run_upload(
    path: str = typer.Argument(..., help="Approved source text file to process"),
    store_path: str = typer.Option(
        "source-intel-reviews.jsonl",
        "--store",
        help="Local JSONL review queue path",
    ),
    source_id: str = typer.Option("approved-upload", "--source-id", help="Source ID"),
    source_name: str = typer.Option("Approved upload", "--source-name", help="Source name"),
    source_url: str | None = typer.Option(None, "--source-url", help="Citation/source URL"),
    authority: str = typer.Option("internal", "--authority", help="official, trusted, internal"),
    topic: Annotated[
        list[str] | None,
        typer.Option("--topic", help="Repeatable topic tag"),
    ] = None,
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Process an approved text upload without network/API access."""
    source_path = Path(path)
    text = source_path.read_text(encoding="utf-8")
    source = SourceDefinition(
        id=source_id,
        name=source_name,
        url=source_url or source_path.as_uri(),
        source_type=SourceType.INTERNAL_UPLOAD,
        authority=authority,
        jurisdictions=[],
        topics=topic or ["approved upload"],
        metadata={"cost": "free", "auth": "none", "upload_path": source_path.name},
    )
    snapshot = SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title=source_name,
        text=text,
        metadata={"upload": True, "filename": source_path.name},
    )
    proposals = SourceIntelEngine(adapters=[RegWatchAdapter(), MicrolearningAdapter()]).evaluate(
        [source],
        [snapshot],
    )
    SourceReviewStore(store_path).save_many(proposals)
    payload = {
        "source_id": source.id,
        "snapshot_count": 1,
        "proposal_count": len(proposals),
        "proposal_ids": [proposal.id for proposal in proposals],
        "proposal_signal_types": [proposal.signal.signal_type for proposal in proposals],
        "store": store_path,
    }
    if json_output:
        _print_json(payload)
        return

    console.print(f"[bold]Source:[/bold] {source.id}")
    console.print("[bold]Snapshots:[/bold] 1")
    console.print(f"[bold]Proposals saved:[/bold] {len(proposals)}")
    console.print(f"[bold]Store:[/bold] {store_path}")


@source_intel_app.command("review")
def source_intel_review(
    store_path: str = typer.Option(
        "source-intel-reviews.jsonl",
        "--store",
        help="Local JSONL review queue path",
    ),
    db_path: str | None = typer.Option(None, "--db", help="Optional SQLite DB review queue"),
    proposal_id: str | None = typer.Option(None, "--proposal-id", help="Proposal ID to decide"),
    state: str | None = typer.Option(None, "--state", help="New review state"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List or update local source-intelligence review proposals."""
    if db_path:
        context = _local_cli_context(role="compliance_manager")
        service = SourceIntelService(LocalRepository(db_path))
        if proposal_id or state:
            if not proposal_id or not state:
                console.print("[red]Both --proposal-id and --state are required to decide.[/red]")
                raise typer.Exit(1)
            try:
                db_proposal = service.decide_proposal(context, proposal_id=proposal_id, state=state)
            except ValueError as exc:
                console.print(f"[red]{exc}[/red]")
                raise typer.Exit(1) from exc
            db_decision_payload: dict[str, Any] = {"proposal": db_proposal}
            if json_output:
                _print_json(db_decision_payload)
                return
            console.print(f"[green]Updated proposal:[/green] {db_proposal['id']}")
            console.print(f"[bold]State:[/bold] {db_proposal['approval_state']}")
            return

        db_proposals = service.list_proposals(context)
        db_list_payload: dict[str, Any] = {"proposals": db_proposals}
        if json_output:
            _print_json(db_list_payload)
            return

        table = Table(title="Source Intelligence DB Review Queue")
        table.add_column("Proposal")
        table.add_column("Adapter")
        table.add_column("Signal")
        table.add_column("State")
        for db_row in db_proposals:
            table.add_row(
                str(db_row["id"]),
                str(db_row["adapter_name"]),
                str(db_row["signal_type"]),
                str(db_row["approval_state"]),
            )
        console.print(table)
        return

    store = SourceReviewStore(store_path)
    if proposal_id or state:
        if not proposal_id or not state:
            console.print("[red]Both --proposal-id and --state are required to decide.[/red]")
            raise typer.Exit(1)
        try:
            jsonl_proposal = store.decide(proposal_id, state=state)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        decision_payload: dict[str, Any] = {"proposal": jsonl_proposal.model_dump(mode="json")}
        if json_output:
            _print_json(decision_payload)
            return
        console.print(f"[green]Updated proposal:[/green] {jsonl_proposal.id}")
        console.print(f"[bold]State:[/bold] {jsonl_proposal.approval_state}")
        return

    proposals = store.list()
    list_payload: dict[str, Any] = {
        "proposals": [proposal.model_dump(mode="json") for proposal in proposals]
    }
    if json_output:
        _print_json(list_payload)
        return

    table = Table(title="Source Intelligence Review Queue")
    table.add_column("Proposal")
    table.add_column("Adapter")
    table.add_column("Signal")
    table.add_column("State")
    for jsonl_row in proposals:
        table.add_row(
            jsonl_row.id,
            jsonl_row.adapter_name,
            jsonl_row.signal.signal_type,
            jsonl_row.approval_state,
        )
    console.print(table)


def _source_intel_notification_events(
    *,
    notification_service: NotificationOutboxService,
    context: ActorContext,
    schedule: dict[str, Any],
    run_id: str,
    summary: dict[str, Any],
    channels: list[str],
) -> list[dict[str, Any]]:
    events = [
        notification_service.enqueue_event(
            context,
            event_type="source_intel.run.completed",
            object_type="source_intel_run",
            object_id=run_id,
            payload={
                "schedule_id": schedule["id"],
                "schedule_name": schedule["name"],
                **summary,
            },
            channels=channels,
        )
    ]
    if int(summary.get("proposal_count", 0)) > 0:
        events.append(
            notification_service.enqueue_event(
                context,
                event_type="source_intel.proposals_waiting",
                object_type="source_intel_run",
                object_id=run_id,
                payload={
                    "schedule_id": schedule["id"],
                    "schedule_name": schedule["name"],
                    "proposal_count": summary["proposal_count"],
                    "query": summary["query"],
                },
                channels=channels,
            )
        )
    if summary.get("coverage_gaps"):
        events.append(
            notification_service.enqueue_event(
                context,
                event_type="source_intel.coverage_gap_found",
                object_type="source_intel_run",
                object_id=run_id,
                payload={
                    "schedule_id": schedule["id"],
                    "schedule_name": schedule["name"],
                    "coverage_gaps": summary["coverage_gaps"],
                    "query": summary["query"],
                },
                channels=channels,
            )
        )
    return events


@source_intel_app.command("schedule-add")
def source_intel_schedule_add(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    name: str = typer.Option(..., "--name", help="Stable schedule name"),
    query: str = typer.Option("training", "--query", help="Source-monitoring query label"),
    interval_hours: int = typer.Option(24, "--interval-hours", help="Run cadence in hours"),
    mode: str = typer.Option("fixture", "--mode", help="Execution mode; fixture is local-only"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Create/update a local source-intelligence schedule without external API setup."""
    context = _local_cli_context(role="compliance_manager")
    try:
        schedule = SourceIntelService(LocalRepository(db_path)).create_schedule(
            context,
            name=name,
            query=query,
            interval_hours=interval_hours,
            source_ids=["fixture-official-training-source"],
            mode=mode,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    payload = {"schedule": schedule}
    if json_output:
        _print_json(payload)
        return
    console.print(f"[green]Schedule saved:[/green] {schedule['name']}")
    console.print(f"[bold]Interval hours:[/bold] {schedule['interval_hours']}")


@source_intel_app.command("schedule-list")
def source_intel_schedule_list(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List local source-intelligence schedules."""
    context = _local_cli_context(role="compliance_manager")
    schedules = SourceIntelService(LocalRepository(db_path)).list_schedules(context)
    payload = {"schedules": schedules}
    if json_output:
        _print_json(payload)
        return

    table = Table(title="Source Intelligence Schedules")
    table.add_column("Name")
    table.add_column("Query")
    table.add_column("Mode")
    table.add_column("Interval")
    table.add_column("Status")
    for schedule in schedules:
        table.add_row(
            str(schedule["name"]),
            str(schedule["query"]),
            str(schedule["mode"]),
            f"{schedule['interval_hours']}h",
            str(schedule["status"]),
        )
    console.print(table)


@source_intel_app.command("run-scheduled")
def source_intel_run_scheduled(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    force: bool = typer.Option(False, "--force", help="Run schedules even when not due"),
    enqueue_notifications: bool = typer.Option(
        True,
        "--enqueue-notifications/--no-enqueue-notifications",
        help="Queue notification events without sending network calls",
    ),
    notify_channel: Annotated[
        list[str] | None,
        typer.Option("--notify-channel", help="Notification channel to enqueue"),
    ] = None,
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Execute due local source-intelligence schedules and record job receipts."""
    context = _local_cli_context(role="compliance_manager")
    repository = LocalRepository(db_path)
    service = SourceIntelService(repository)
    notification_service = NotificationOutboxService(repository)
    schedules = service.due_schedules(context, force=force)
    executions = []
    notification_events = []
    channels = notify_channel or ["slack", "teams"]
    for schedule in schedules:
        started_at = utc_now()
        run_id = None
        try:
            if schedule["mode"] != "fixture":
                raise ValueError(f"unsupported schedule mode: {schedule['mode']}")
            run = _run_fixture_source_monitor(str(schedule["query"]))
            receipt = service.record_run(context, query=str(schedule["query"]), run=run)
            run_id = str(receipt["run_id"])
            summary = {
                "schedule_name": schedule["name"],
                "query": schedule["query"],
                "source_count": run.source_count,
                "snapshot_count": run.snapshot_count,
                "proposal_count": run.proposal_count,
                "coverage_gaps": run.coverage_gaps,
            }
            execution = service.record_schedule_execution(
                context,
                schedule_id=str(schedule["id"]),
                run_id=run_id,
                status="succeeded",
                started_at=started_at,
                finished_at=utc_now(),
                summary=summary,
            )
            if enqueue_notifications:
                notification_events.extend(
                    _source_intel_notification_events(
                        notification_service=notification_service,
                        context=context,
                        schedule=schedule,
                        run_id=run_id,
                        summary=summary,
                        channels=channels,
                    )
                )
        except Exception as exc:
            execution = service.record_schedule_execution(
                context,
                schedule_id=str(schedule["id"]),
                run_id=run_id,
                status="failed",
                started_at=started_at,
                finished_at=utc_now(),
                summary={"schedule_name": schedule["name"], "query": schedule["query"]},
                error=str(exc),
            )
        executions.append(execution)

    payload = {
        "scheduled_count": len(schedules),
        "executions": executions,
        "notification_events": notification_events,
    }
    if json_output:
        _print_json(payload)
        return

    console.print(f"[bold]Schedules executed:[/bold] {len(executions)}")
    for execution in executions:
        console.print(f"  {execution['schedule_id']}: {execution['status']}")


@source_intel_app.command("export-packet")
def source_intel_export_packet(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    output_path: str | None = typer.Option(None, "--output", help="Optional JSON output path"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Export a source-intelligence review/audit packet for human review."""
    context = _local_cli_context(role="compliance_manager")
    packet = SourceIntelService(LocalRepository(db_path)).export_review_packet(context)
    if output_path:
        Path(output_path).write_text(
            json.dumps(packet, indent=2, default=str),
            encoding="utf-8",
        )
    payload = {"packet": packet, "output": output_path}
    if json_output:
        _print_json(payload)
        return
    console.print(f"[bold]Source-intelligence proposals:[/bold] {packet['proposal_count']}")
    if output_path:
        console.print(f"[bold]Packet written:[/bold] {output_path}")


@admin_app.command("roles")
def admin_roles(json_output: bool = typer.Option(False, "--json", help="Output raw JSON")):
    """Show default roles and permissions."""
    data = {role: sorted(permissions) for role, permissions in ROLE_PERMISSIONS.items()}
    if json_output:
        _print_json(data)
        return

    table = Table(title="Default Roles")
    table.add_column("Role")
    table.add_column("Permissions")
    for role, permissions in data.items():
        table.add_row(role, ", ".join(permissions))
    console.print(table)


@admin_role_bindings_app.command("list")
def admin_role_bindings_list(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    actor_id: str | None = typer.Option(None, "--actor-id", help="Filter by actor ID"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List tenant-scoped role bindings for the local operator's tenant."""
    context = _local_cli_context()
    bindings = RoleAdminService(LocalRepository(db_path)).list_role_bindings(
        context,
        actor_id=actor_id,
    )
    payload = {"role_bindings": bindings}
    if json_output:
        _print_json(payload)
        return

    table = Table(title="Role Bindings")
    table.add_column("Actor")
    table.add_column("Role")
    table.add_column("Override")
    table.add_column("Created By")
    for binding in bindings:
        override = binding.get("permissions_override") or []
        table.add_row(
            str(binding["actor_id"]),
            str(binding["role"]),
            ", ".join(override) if override else "—",
            str(binding.get("created_by") or "—"),
        )
    console.print(table)


@admin_role_bindings_app.command("set")
def admin_role_bindings_set(
    actor_id: str = typer.Argument(..., help="Actor ID to bind"),
    role: str = typer.Option(..., "--role", help="Role name"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Create or replace a tenant-scoped role binding for an actor."""
    context = _local_cli_context()
    try:
        binding = RoleAdminService(LocalRepository(db_path)).set_role_binding(
            context,
            actor_id=actor_id,
            role=role,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if json_output:
        _print_json(binding)
        return
    console.print(f"[green]Bound actor {binding['actor_id']} to role {binding['role']}[/green]")


@admin_role_bindings_app.command("remove")
def admin_role_bindings_remove(
    actor_id: str = typer.Argument(..., help="Actor ID to unbind"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Remove a tenant-scoped role binding for an actor."""
    context = _local_cli_context()
    try:
        result = RoleAdminService(LocalRepository(db_path)).remove_role_binding(
            context,
            actor_id=actor_id,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    if json_output:
        _print_json(result)
        return
    console.print(f"[green]Removed role binding for actor {actor_id}[/green]")


@security_app.command("evidence")
def security_evidence(
    period: str = typer.Option("current", "--period", help="Evidence period label"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Collect a readiness-only security evidence packet."""
    context = _local_cli_context(track=track, role="compliance_manager")
    result = SecurityEvidenceService(LocalRepository(db_path)).collect_packet(
        context,
        period=period,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Security evidence period:[/bold] {result.period}")
    console.print(f"[bold]Posture:[/bold] {result.posture}")
    console.print(f"[bold]Summary:[/bold] {result.summary}")


@notifications_app.command("list")
def notifications_list(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    limit: int = typer.Option(50, "--limit", help="Maximum pending deliveries to list"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List pending notification outbox deliveries without exposing webhook URLs."""
    context = _local_cli_context(role="compliance_manager")
    deliveries = NotificationOutboxService(LocalRepository(db_path)).list_pending_deliveries(
        context,
        limit=limit,
    )
    payload = {"pending_count": len(deliveries), "deliveries": deliveries}
    if json_output:
        _print_json(payload)
        return

    table = Table(title="Notification Outbox")
    table.add_column("Delivery")
    table.add_column("Channel")
    table.add_column("Event")
    table.add_column("Status")
    for delivery in deliveries:
        event = delivery.get("event") or {}
        table.add_row(
            str(delivery["id"]),
            str(delivery["channel"]),
            str(event.get("event_type", "unknown")),
            str(delivery["status"]),
        )
    console.print(table)


@notifications_app.command("preferences")
def notifications_preferences(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """List tenant notification preferences and kill switches."""
    context = _local_cli_context(role="compliance_manager")
    preferences = NotificationOutboxService(LocalRepository(db_path)).list_preferences(context)
    payload = {"preferences": preferences}
    if json_output:
        _print_json(payload)
        return

    table = Table(title="Notification Preferences")
    table.add_column("Channel")
    table.add_column("Event")
    table.add_column("Enabled")
    table.add_column("Reason")
    for preference in preferences:
        table.add_row(
            str(preference["channel"]),
            str(preference["event_type"]),
            "yes" if preference["enabled"] else "no",
            str(preference.get("reason") or ""),
        )
    console.print(table)


@notifications_app.command("preference-set")
def notifications_preference_set(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    channel: str = typer.Option(..., "--channel", help="Channel name or '*'"),
    event_type: str = typer.Option("*", "--event-type", help="Event type or '*'"),
    enabled: bool = typer.Option(
        True,
        "--enabled/--disabled",
        help="Enable or disable this channel/event route",
    ),
    reason: str | None = typer.Option(None, "--reason", help="Human-readable change reason"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Set a channel/event notification preference for the current tenant."""
    context = _local_cli_context(role="compliance_manager")
    preference = NotificationOutboxService(LocalRepository(db_path)).set_preference(
        context,
        channel=channel,
        event_type=event_type,
        enabled=enabled,
        reason=reason,
    )
    if json_output:
        _print_json(preference)
        return
    console.print(
        f"[green]Notification preference saved:[/green] "
        f"{preference['channel']} / {preference['event_type']} "
        f"{'enabled' if preference['enabled'] else 'disabled'}"
    )


@notifications_app.command("drain")
def notifications_drain(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--send",
        help="Preview by default; use --send to perform outbound webhook calls",
    ),
    limit: int = typer.Option(50, "--limit", help="Maximum pending deliveries to drain"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Drain pending notification deliveries through configured hook channels."""
    context = _local_cli_context(role="compliance_manager")
    service = NotificationOutboxService(LocalRepository(db_path))
    deliveries = service.list_pending_deliveries(context, limit=limit)
    results: list[dict[str, Any]] = []

    async def _send_all() -> list[dict[str, Any]]:
        webhook_sender = _get_outbox_sender()
        email_sender = _get_email_outbox_sender()
        sent_results: list[dict[str, Any]] = []
        for delivery in deliveries:
            try:
                sender = (
                    email_sender if str(delivery["channel"]).lower() == "email" else webhook_sender
                )
                result = await sender.send_delivery(delivery)
            except Exception as exc:
                marked = service.mark_delivery_failed(
                    context,
                    delivery_id=str(delivery["id"]),
                    error=str(exc),
                )
                sent_results.append({"delivery": marked, "status": marked["status"]})
                continue

            if result.get("skipped"):
                marked = service.mark_delivery_skipped(
                    context,
                    delivery_id=str(delivery["id"]),
                    error=str(result["error"]),
                )
            elif not result.get("sent"):
                marked = service.mark_delivery_failed(
                    context,
                    delivery_id=str(delivery["id"]),
                    error=str(result.get("error", "notification delivery failed")),
                )
            else:
                marked = service.mark_delivery_sent(
                    context,
                    delivery_id=str(delivery["id"]),
                    response_metadata={
                        "status_code": result.get("status_code"),
                        "recipient_count": result.get("recipient_count"),
                    },
                )
            sent_results.append({"delivery": marked, "status": marked["status"]})
        return sent_results

    if dry_run:
        results = [
            {
                "delivery": delivery,
                "status": "would_send",
            }
            for delivery in deliveries
        ]
    else:
        results = asyncio.run(_send_all())

    payload = {
        "dry_run": dry_run,
        "pending_count": len(deliveries),
        "deliveries": results,
    }
    if json_output:
        _print_json(payload)
        return

    table = Table(title="Notification Drain")
    table.add_column("Delivery")
    table.add_column("Channel")
    table.add_column("Status")
    for item in results:
        delivery = item["delivery"]
        table.add_row(str(delivery["id"]), str(delivery["channel"]), str(item["status"]))
    console.print(table)


@governance_app.command("packet")
def governance_packet(
    lane: str = typer.Option("workforce", "--lane", help="workforce, campus, or combined"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Collect AI, HR-boundary, and school-readiness governance packet."""
    context = _local_cli_context(track=track, role="compliance_manager")
    result = GovernancePacketService(LocalRepository(db_path)).collect_packet(
        context,
        lane=lane,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Governance lane:[/bold] {result.lane}")
    console.print(f"[bold]Posture:[/bold] {result.posture}")
    console.print(f"[bold]Summary:[/bold] {result.summary}")


@privacy_app.command("request")
def privacy_request(
    subject_id: str = typer.Argument(..., help="Subject/user identifier"),
    request_type: str = typer.Option("access", "--type", help="access/export/correction/deletion"),
    region: str | None = typer.Option(None, "--region", help="Region or jurisdiction"),
    notes: str | None = typer.Option(None, "--notes", help="Internal request notes"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Create a privacy/data-subject request case."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).create_request(
        context,
        subject_id=subject_id,
        request_type=request_type,
        region=region,
        notes=notes,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Privacy request:[/bold] {result.request_id}")
    console.print(f"[bold]Subject:[/bold] {result.subject_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")


@privacy_app.command("approve")
def privacy_approve(
    request_id: str = typer.Argument(..., help="Privacy request ID"),
    note: str | None = typer.Option(None, "--note", help="Controller approval note"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Record controller approval before export/delete processing."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).approve_request(
        context,
        request_id,
        approval_note=note,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Privacy request:[/bold] {result.request_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")


@privacy_app.command("export")
def privacy_export(
    request_id: str = typer.Argument(..., help="Privacy request ID"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Export subject data for an approved privacy request."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).export_subject(context, request_id)
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Privacy request:[/bold] {result.request_id}")
    console.print(f"[bold]Subject records:[/bold] {result.record_counts}")


@privacy_app.command("delete")
def privacy_delete(
    request_id: str = typer.Argument(..., help="Privacy request ID"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Delete/anonymize subject records unless blocked by legal hold."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).delete_subject(context, request_id)
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Privacy request:[/bold] {result.request_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")
    if result.blocked_by_holds:
        hold_ids = ", ".join(result.blocked_by_holds)
        console.print(f"[yellow]Blocked by legal holds:[/yellow] {hold_ids}")


@privacy_app.command("legal-hold")
def privacy_legal_hold(
    subject_id: str = typer.Argument(..., help="Subject/user identifier"),
    scope: str = typer.Option("subject", "--scope", help="subject, tenant, or system"),
    reason: str = typer.Option(..., "--reason", help="Reason for legal hold"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Create an active legal hold that blocks deletion."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).create_legal_hold(
        context,
        subject_id=subject_id,
        scope=scope,
        reason=reason,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Legal hold:[/bold] {result.hold_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")


@privacy_app.command("release-hold")
def privacy_release_hold(
    hold_id: str = typer.Argument(..., help="Legal hold ID"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Release a legal hold."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).release_legal_hold(context, hold_id)
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Legal hold:[/bold] {result.hold_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")


@privacy_retention_app.command("configure")
def privacy_retention_configure(
    raw_import_days: int = typer.Option(..., "--raw-import-days"),
    evidence_days: int = typer.Option(..., "--evidence-days"),
    action_log_days: int = typer.Option(..., "--action-log-days"),
    ai_proposal_days: int = typer.Option(..., "--ai-proposal-days"),
    privacy_request_days: int = typer.Option(365, "--privacy-request-days"),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Configure tenant retention settings for privacy program evidence."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).configure_retention_policy(
        context,
        raw_import_days=raw_import_days,
        evidence_days=evidence_days,
        action_log_days=action_log_days,
        ai_proposal_days=ai_proposal_days,
        privacy_request_days=privacy_request_days,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    console.print(f"[bold]Tenant:[/bold] {result.tenant_id}")
    console.print(f"[bold]Policy:[/bold] {result.policy}")


@privacy_retention_app.command("run")
def privacy_retention_run(
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--apply",
        help="Preview cleanup by default; use --apply to delete eligible closed cases",
    ),
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
    track: str = typer.Option("workforce", "--track", help="workforce or campus"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Run retention cleanup for closed privacy program artifacts."""
    context = _local_cli_context(track=track, role="privacy_admin")
    result = PrivacyProgramService(LocalRepository(db_path)).run_retention_cleanup(
        context,
        dry_run=dry_run,
    )
    if json_output:
        _print_json(result.model_dump(mode="json"))
        return
    mode = "dry-run" if result.dry_run else "apply"
    console.print(f"[bold]Retention run:[/bold] {mode}")
    console.print(f"[bold]Eligible:[/bold] {result.eligible_counts}")
    console.print(f"[bold]Deleted:[/bold] {result.deleted_counts}")


@app.command("deployment-check")
def deployment_check(
    root: str = typer.Option(".", "--root", help="Repository root to inspect"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Run deployment/observability checks for release hardening."""
    checklist = build_deployment_checklist(Path(root))
    payload = {
        "ready": all(item["ok"] for item in checklist),
        "checks": checklist,
    }
    if json_output:
        _print_json(payload)
        return

    table = Table(title="Deployment Hardening Checks")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Message")
    for item in checklist:
        table.add_row(
            item["label"],
            "ok" if item["ok"] else "missing",
            item["message"],
        )
    console.print(table)


privacy_app.add_typer(privacy_retention_app, name="retention")
app.add_typer(import_app, name="import")
app.add_typer(evidence_app, name="evidence")
app.add_typer(ai_app, name="ai")
app.add_typer(source_intel_app, name="source-intel")
admin_app.add_typer(admin_role_bindings_app, name="role-bindings")
app.add_typer(admin_app, name="admin")
app.add_typer(governance_app, name="governance")
app.add_typer(security_app, name="security")
app.add_typer(notifications_app, name="notifications")
app.add_typer(privacy_app, name="privacy")


if __name__ == "__main__":
    app()
