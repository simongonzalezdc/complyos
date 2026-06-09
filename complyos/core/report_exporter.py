"""Export audit reports to HTML."""

from __future__ import annotations

from typing import Any

from complyos.models.domain import AuditReport

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ComplyOS Audit Report</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card: #1e293b;
            --text: #f1f5f9;
            --muted: #94a3b8;
            --accent: #38bdf8;
            --critical: #ef4444;
            --high: #f97316;
            --medium: #eab308;
            --low: #22c55e;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            padding: 2rem;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        .meta {{ color: var(--muted); margin-bottom: 2rem; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        .card {{
            background: var(--card);
            border-radius: 0.75rem;
            padding: 1.5rem;
            border: 1px solid #334155;
        }}
        .card h3 {{
            font-size: 0.875rem; color: var(--muted); margin-bottom: 0.5rem;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        .card .value {{ font-size: 2rem; font-weight: 700; }}
        .severity-critical {{ color: var(--critical); }}
        .severity-high {{ color: var(--high); }}
        .severity-medium {{ color: var(--medium); }}
        .severity-low {{ color: var(--low); }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--card);
            border-radius: 0.75rem;
            overflow: hidden;
            margin-bottom: 2rem;
        }}
        th, td {{ padding: 0.875rem 1rem; text-align: left; }}
        th {{
            background: #334155; font-size: 0.75rem;
            text-transform: uppercase; letter-spacing: 0.05em;
            color: var(--muted);
        }}
        tr {{ border-bottom: 1px solid #334155; }}
        tr:last-child {{ border-bottom: none; }}
        .badge {{
            display: inline-block;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
        }}
        .badge-critical {{ background: rgba(239, 68, 68, 0.2); color: var(--critical); }}
        .badge-high {{ background: rgba(249, 115, 22, 0.2); color: var(--high); }}
        .badge-medium {{ background: rgba(234, 179, 8, 0.2); color: var(--medium); }}
        .badge-low {{ background: rgba(34, 197, 94, 0.2); color: var(--low); }}
        .evidence {{
            background: var(--card);
            border-radius: 0.75rem;
            padding: 1.5rem;
            border: 1px solid #334155;
            font-family: monospace;
            font-size: 0.875rem;
            color: var(--muted);
            word-break: break-all;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>ComplyOS Audit Report</h1>
        <p class="meta">Generated at {generated_at} &middot; Scope: {scope}</p>

        <div class="grid">
            <div class="card">
                <h3>Users Audited</h3>
                <div class="value">{total_users}</div>
            </div>
            <div class="card">
                <h3>Gaps Found</h3>
                <div class="value">{gaps_found}</div>
            </div>
            <div class="card">
                <h3>Critical</h3>
                <div class="value severity-critical">{critical_count}</div>
            </div>
            <div class="card">
                <h3>High</h3>
                <div class="value severity-high">{high_count}</div>
            </div>
            <div class="card">
                <h3>Medium</h3>
                <div class="value severity-medium">{medium_count}</div>
            </div>
            <div class="card">
                <h3>Low</h3>
                <div class="value severity-low">{low_count}</div>
            </div>
        </div>

        <h2>Gaps by Department</h2>
        <table>
            <thead>
                <tr><th>Department</th><th>Gaps</th></tr>
            </thead>
            <tbody>
                {dept_rows}
            </tbody>
        </table>

        <h2>Compliance Gaps</h2>
        <table>
            <thead>
                <tr>
                    <th>User</th>
                    <th>Department</th>
                    <th>Missing Courses</th>
                    <th>Severity</th>
                    <th>Days Overdue</th>
                </tr>
            </thead>
            <tbody>
                {gap_rows}
            </tbody>
        </table>

        <h2>Evidence Ledger</h2>
        <div class="evidence">{evidence_hash}</div>
    </div>
</body>
</html>
"""


def export_html(report: AuditReport, output_path: str = "report.html") -> str:
    """Export an AuditReport to a styled HTML file.

    Returns the path to the generated file.
    """
    severity_counts = report.gaps_by_severity
    dept_rows = "\n".join(
        f"<tr><td>{dept}</td><td>{count}</td></tr>"
        for dept, count in report.gaps_by_department.items()
    )
    if not dept_rows:
        dept_rows = '<tr><td colspan="2">No gaps found</td></tr>'

    gap_rows = "\n".join(
        _gap_row(gap) for gap in report.details
    )
    if not gap_rows:
        gap_rows = '<tr><td colspan="5">No gaps found</td></tr>'

    html = HTML_TEMPLATE.format(
        generated_at=report.generated_at.isoformat(),
        scope=report.scope or "all",
        total_users=report.total_users_audited,
        gaps_found=report.gaps_found,
        critical_count=severity_counts.get("critical", 0),
        high_count=severity_counts.get("high", 0),
        medium_count=severity_counts.get("medium", 0),
        low_count=severity_counts.get("low", 0),
        dept_rows=dept_rows,
        gap_rows=gap_rows,
        evidence_hash=report.evidence_hash,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _gap_row(gap: Any) -> str:
    severity = gap.severity
    badge_class = f"badge-{severity}"
    courses = ", ".join(c.title for c in gap.missing_courses)
    overdue = str(gap.days_overdue) if gap.days_overdue else "—"
    return (
        f"<tr>"
        f"<td>{gap.user.first_name} {gap.user.last_name}</td>"
        f"<td>{gap.user.department}</td>"
        f"<td>{courses}</td>"
        f'<td><span class="badge {badge_class}">{severity}</span></td>'
        f"<td>{overdue}</td>"
        f"</tr>"
    )
