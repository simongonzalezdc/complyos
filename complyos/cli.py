"""CLI entry point for ComplyOS."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer
import yaml
from rich.console import Console
from rich.table import Table

from complyos.api.mcp_server import (
    _get_connector,
    audit_compliance_gaps,
    check_connector_health,
    generate_audit_report,
    get_user_compliance_status,
)
from complyos.config import ComplyOSConfig
from complyos.core.remediation import RemediationEngine
from complyos.core.report_exporter import export_html
from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import AssignmentRule
from complyos.notification.sender import NotificationSender
from complyos.notification.webhooks import WebhookNotifier

app = typer.Typer(name="complyos", help="L&D Compliance & Learning Operations")
console = Console()


def _get_notifier() -> NotificationSender | None:
    """Build a NotificationSender from environment or return None."""
    import os

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


def _get_webhook_notifier() -> WebhookNotifier | None:
    """Build a webhook notifier from environment or return None."""
    slack_url = os.getenv("COMPLYOS_SLACK_WEBHOOK_URL")
    teams_url = os.getenv("COMPLYOS_TEAMS_WEBHOOK_URL")
    if not slack_url and not teams_url:
        return None
    return WebhookNotifier(slack_webhook_url=slack_url, teams_webhook_url=teams_url)


@app.command()
def audit(
    department: str | None = typer.Option(None, "--department", "-d", help="Filter by department"),
    region: str | None = typer.Option(None, "--region", "-r", help="Filter by region"),
    json_output: bool = typer.Option(False, "--json", help="Output raw JSON"),
):
    """Audit compliance training gaps."""
    result = asyncio.run(audit_compliance_gaps(department=department, region=region))

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
    result = asyncio.run(generate_audit_report(department=department, region=region))

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
    result = asyncio.run(get_user_compliance_status(user_id))

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
    from complyos.api.mcp_server import generate_compliance_digest

    result = asyncio.run(
        generate_compliance_digest(department=department, region=region, db_path=db_path)
    )

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
    result = asyncio.run(check_connector_health())

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
    from complyos.connectors.capabilities import list_connector_capabilities

    try:
        items = list_connector_capabilities(profile=profile)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    if json_output:
        console.print(json.dumps([item.to_dict() for item in items], indent=2))
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
            item.name,
            item.profile,
            item.status,
            item.auth,
            "yes" if item.supports_learning_records else "no",
            "yes" if item.supports_due_dates else "no",
            "yes" if item.supports_expiry else "no",
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


@app.command("run-schedule")
def run_schedule(
    config_path: str = typer.Option("complyos.yaml", "--config", help="Config file with schedule.jobs"),
    db_path: str | None = typer.Option(None, "--db", help="Path to SQLite database"),
    force: bool = typer.Option(False, "--force", help="Run jobs even when last_run_at is not due"),
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
    engine = AssignmentRuleEngine(LocalRepository(db_path))
    result = engine.validate_rule(rule)

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
    engine = AssignmentRuleEngine(LocalRepository(db_path))
    result = engine.preview_rule(rule)

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
    from complyos.api.mcp_server import _get_auditor, _get_connector

    async def _remediate():
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

        return gaps, actions, ledger

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
    from complyos.api.mcp_server import _get_auditor

    async def _export():
        auditor = _get_auditor()
        report = await auditor.generate_report(department=department, region=region)
        return report

    report = asyncio.run(_export())
    path = export_html(report, output)
    console.print(f"[green]Report exported to {path}[/green]")


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


if __name__ == "__main__":
    app()
