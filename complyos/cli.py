"""CLI entry point for ComplyOS."""

from __future__ import annotations

import asyncio
import json

import typer
from rich.console import Console
from rich.table import Table

from complyos.api.mcp_server import (
    _get_connector,
    audit_compliance_gaps,
    check_connector_health,
    generate_audit_report,
    get_user_compliance_status,
)
from complyos.core.repository import LocalRepository

app = typer.Typer(name="complyos", help="L&D Compliance & Learning Operations")
console = Console()


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
def sync(
    db_path: str = typer.Option("complyos.db", "--db", help="Path to SQLite database"),
):
    """Sync LMS data into local SQLite cache."""
    connector = _get_connector()
    repo = LocalRepository(db_path)

    async def _sync():
        healthy = await connector.authenticate()
        if not healthy:
            console.print("[red]Connector authentication failed[/red]")
            raise typer.Exit(1)

        console.print(f"[bold]Syncing from {connector.name}...[/bold]")

        users = await connector.get_users()
        courses = await connector.get_courses()
        enrollments = await connector.get_enrollments()

        repo.clear_all()
        repo.sync_users(users)
        repo.sync_courses(courses)
        repo.sync_enrollments(enrollments)

        return len(users), len(courses), len(enrollments)

    user_count, course_count, enrollment_count = asyncio.run(_sync())
    console.print(
        f"[green]Synced {user_count} users, {course_count} courses, "
        f"{enrollment_count} enrollments[/green]"
    )


@app.command()
def mcp():
    """Run the MCP server."""
    from complyos.api.mcp_server import main
    main()


if __name__ == "__main__":
    app()
