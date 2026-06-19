"""Export audit reports to HTML, plus the shared safe-cell neutralization.

``_neutralize_formula`` is the single home for spreadsheet formula-injection
defense: it prefixes a leading dangerous character with a quote so a cell can
never execute when opened or pasted into Excel/Sheets/Numbers. The HTML export
layers HTML-escaping on top via ``_safe_cell``; the CSV/BI export reuses the
same neutralization (the ``csv`` module owns CSV quoting, so no HTML-escape).
"""

from __future__ import annotations

import csv
import io
from html import escape as _html_escape
from typing import Any

from complyos.models.domain import AuditReport

# Spreadsheet apps (Excel/Sheets/Numbers) treat a cell whose text begins with
# any of these as a live formula. A report that round-trips through CSV/clipboard
# must neutralize them so attacker-controlled learner/source fields cannot run.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _neutralize_formula(value: object) -> str:
    """Quote-prefix a value if it would be read as a spreadsheet formula.

    The single source of truth for formula-injection neutralization, shared by
    the HTML and CSV/BI export paths so the defense can never drift between them.
    """
    text = "" if value is None else str(value)
    if text and text[0] in _FORMULA_PREFIXES:
        text = "'" + text
    return text


def _safe_cell(value: object) -> str:
    """Escape a user/source-derived field for inclusion in exported HTML.

    Neutralizes spreadsheet formula injection (prefixes the value with a single
    quote so Excel/Sheets treat it as text) and HTML-escapes it so it cannot
    inject markup/script into the rendered report. Applied to every field that
    originates from LMS/import data rather than from ComplyOS itself.
    """
    return _html_escape(_neutralize_formula(value), quote=True)


def write_safe_csv(
    columns: list[str],
    rows: list[dict[str, object]],
) -> str:
    """Render rows to a CSV string with every cell formula-neutralized.

    Column order is fixed by ``columns`` so a BI/spreadsheet consumer sees a
    stable schema. Every value is run through ``_neutralize_formula`` before the
    ``csv`` writer quotes it, so an attacker-controlled field beginning with
    ``=``/``+``/``-``/``@`` (or a leading tab/CR) lands as inert text, not a live
    formula. The ``csv`` module owns CSV-level quoting/escaping; this never
    hand-rolls delimiter handling.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_neutralize_formula(row.get(column, "")) for column in columns])
    return buffer.getvalue()

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


def render_html(report: AuditReport) -> str:
    """Render an AuditReport to a styled HTML string (no disk write).

    This is the in-memory half of the export so a remote surface (API) can
    return report content in the response body without writing to server disk,
    while file-writing surfaces (CLI/MCP) reuse it via ``export_html``.
    """
    severity_counts = report.gaps_by_severity
    dept_rows = "\n".join(
        f"<tr><td>{_safe_cell(dept)}</td><td>{int(count)}</td></tr>"
        for dept, count in report.gaps_by_department.items()
    )
    if not dept_rows:
        dept_rows = '<tr><td colspan="2">No gaps found</td></tr>'

    gap_rows = "\n".join(
        _gap_row(gap) for gap in report.details
    )
    if not gap_rows:
        gap_rows = '<tr><td colspan="5">No gaps found</td></tr>'

    return HTML_TEMPLATE.format(
        generated_at=report.generated_at.isoformat(),
        scope=_safe_cell(report.scope or "all"),
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


def export_html(report: AuditReport, output_path: str = "report.html") -> str:
    """Export an AuditReport to a styled HTML file.

    Returns the path to the generated file.
    """
    html = render_html(report)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    return output_path


def _gap_row(gap: Any) -> str:
    severity = gap.severity
    # severity drives a CSS class, so it is escaped both as the class token and
    # as visible text to keep an unexpected value from breaking out of the tag.
    badge_class = f"badge-{_safe_cell(severity)}"
    courses = ", ".join(_safe_cell(c.title) for c in gap.missing_courses)
    overdue = str(int(gap.days_overdue)) if gap.days_overdue else "—"
    return (
        f"<tr>"
        f"<td>{_safe_cell(gap.user.first_name)} {_safe_cell(gap.user.last_name)}</td>"
        f"<td>{_safe_cell(gap.user.department)}</td>"
        f"<td>{courses}</td>"
        f'<td><span class="badge {badge_class}">{_safe_cell(severity)}</span></td>'
        f"<td>{overdue}</td>"
        f"</tr>"
    )
