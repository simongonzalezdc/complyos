"""Generate a self-contained, read-only HTML compliance dashboard.

Combines the current audit with snapshot history (recorded by digest
runs) into a single static file: summary cards, severity breakdown,
department bars, a gap-count trend line, and a filterable gaps table.
No server, no external assets — open the file in any browser.
"""

from __future__ import annotations

import html
from typing import Any

from complyos.models.domain import AuditReport

SEVERITY_ORDER = ["critical", "high", "medium", "low"]

# Trend chart geometry (SVG user units)
CHART_WIDTH = 640
CHART_HEIGHT = 120
CHART_PAD = 12

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ComplyOS Dashboard</title>
    <style>
        :root {{
            --bg: #0f172a;
            --card: #1e293b;
            --border: #334155;
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
        .skip-link {{
            position: absolute; left: -9999px;
            background: var(--accent); color: var(--bg);
            padding: 0.5rem 1rem; border-radius: 0.5rem; z-index: 10;
        }}
        .skip-link:focus {{ left: 1rem; top: 1rem; }}
        :focus-visible {{ outline: 2px solid var(--accent); outline-offset: 2px; }}
        main {{ max-width: 1200px; margin: 0 auto; }}
        h1 {{ font-size: 2rem; margin-bottom: 0.5rem; }}
        h2 {{ font-size: 1.25rem; margin: 2rem 0 1rem; }}
        .meta {{ color: var(--muted); margin-bottom: 2rem; }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 1rem;
        }}
        .card {{
            background: var(--card);
            border-radius: 0.75rem;
            padding: 1.25rem 1.5rem;
            border: 1px solid var(--border);
        }}
        .card h3 {{
            font-size: 0.8125rem; color: var(--muted); margin-bottom: 0.25rem;
            text-transform: uppercase; letter-spacing: 0.05em;
        }}
        .card .value {{ font-size: 2rem; font-weight: 700; }}
        .severity-critical {{ color: var(--critical); }}
        .severity-high {{ color: var(--high); }}
        .severity-medium {{ color: var(--medium); }}
        .severity-low {{ color: var(--low); }}
        .panel {{
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 0.75rem;
            padding: 1.5rem;
        }}
        .bar-row {{ display: flex; align-items: center; gap: 0.75rem; margin: 0.5rem 0; }}
        .bar-label {{ flex: 0 0 10rem; font-size: 0.875rem; color: var(--text); }}
        .bar-track {{ flex: 1; background: var(--bg); border-radius: 9999px; height: 1.25rem; }}
        .bar-fill {{
            background: var(--accent); height: 100%; border-radius: 9999px;
            min-width: 2px;
        }}
        .bar-count {{ flex: 0 0 2.5rem; font-size: 0.875rem; color: var(--muted); }}
        .controls {{ display: flex; gap: 1rem; margin-bottom: 1rem; flex-wrap: wrap; }}
        .controls label {{ font-size: 0.875rem; color: var(--muted); display: block; }}
        .controls input, .controls select {{
            background: var(--card); color: var(--text);
            border: 1px solid var(--border); border-radius: 0.5rem;
            padding: 0.5rem 0.75rem; font-size: 0.9375rem; min-width: 14rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: var(--card);
            border-radius: 0.75rem;
            overflow: hidden;
        }}
        th, td {{ padding: 0.875rem 1rem; text-align: left; }}
        th {{
            background: var(--border); font-size: 0.75rem;
            text-transform: uppercase; letter-spacing: 0.05em;
            color: var(--muted);
        }}
        tr {{ border-bottom: 1px solid var(--border); }}
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
            font-family: monospace; font-size: 0.875rem;
            color: var(--muted); word-break: break-all;
        }}
        .empty {{ color: var(--muted); font-size: 0.9375rem; }}
        @media (prefers-reduced-motion: no-preference) {{
            .bar-fill {{ transition: width 0.4s ease; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            * {{ transition: none !important; animation: none !important; }}
        }}
    </style>
</head>
<body>
    <a class="skip-link" href="#gaps">Skip to compliance gaps</a>
    <main>
        <h1>ComplyOS Dashboard</h1>
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

        <h2>Gap Trend</h2>
        <div class="panel">{trend_section}</div>

        <h2>Gaps by Department</h2>
        <div class="panel">{dept_bars}</div>

        <h2 id="gaps">Compliance Gaps</h2>
        <div class="controls">
            <div>
                <label for="filter-text">Filter by user, department, or course</label>
                <input id="filter-text" type="search" placeholder="Start typing to filter...">
            </div>
            <div>
                <label for="filter-severity">Severity</label>
                <select id="filter-severity">
                    <option value="">All severities</option>
                    <option value="critical">Critical</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                </select>
            </div>
        </div>
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
            <tbody id="gaps-body">
                {gap_rows}
            </tbody>
        </table>

        <h2>Evidence Ledger</h2>
        <div class="panel evidence">{evidence_hash}</div>
    </main>
    <script>
        (function () {{
            var textInput = document.getElementById("filter-text");
            var severitySelect = document.getElementById("filter-severity");
            var rows = document.querySelectorAll("#gaps-body tr[data-severity]");

            function applyFilters() {{
                var query = textInput.value.toLowerCase();
                var severity = severitySelect.value;
                rows.forEach(function (row) {{
                    var matchesText = row.textContent.toLowerCase().indexOf(query) !== -1;
                    var matchesSeverity = !severity || row.dataset.severity === severity;
                    row.hidden = !(matchesText && matchesSeverity);
                }});
            }}

            textInput.addEventListener("input", applyFilters);
            severitySelect.addEventListener("change", applyFilters);
        }})();
    </script>
</body>
</html>
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _gap_row(gap: Any) -> str:
    severity = _esc(gap.severity)
    courses = ", ".join(_esc(c.title) for c in gap.missing_courses)
    overdue = str(gap.days_overdue) if gap.days_overdue else "—"
    return (
        f'<tr data-severity="{severity}">'
        f"<td>{_esc(gap.user.full_name)}</td>"
        f"<td>{_esc(gap.user.department)}</td>"
        f"<td>{courses}</td>"
        f'<td><span class="badge badge-{severity}">{severity}</span></td>'
        f"<td>{overdue}</td>"
        f"</tr>"
    )


def _dept_bars(gaps_by_department: dict[str, int]) -> str:
    if not gaps_by_department:
        return '<p class="empty">No gaps in any department.</p>'
    peak = max(gaps_by_department.values())
    rows = []
    for dept, count in sorted(gaps_by_department.items(), key=lambda x: x[1], reverse=True):
        width = round(count / peak * 100) if peak else 0
        rows.append(
            f'<div class="bar-row">'
            f'<span class="bar-label">{_esc(dept)}</span>'
            f'<div class="bar-track" role="img" '
            f'aria-label="{_esc(dept)}: {count} gaps">'
            f'<div class="bar-fill" style="width: {width}%"></div></div>'
            f'<span class="bar-count">{count}</span>'
            f"</div>"
        )
    return "\n".join(rows)


def _trend_section(history: list[dict[str, Any]], current_gaps: int) -> str:
    """Render an SVG line of gaps_found over time from snapshot history.

    History is expected newest-first (as returned by the repository);
    the current audit is appended as the final point.
    """
    points = [s["gaps_found"] for s in reversed(history)]
    points.append(current_gaps)
    if len(points) < 2:
        return (
            '<p class="empty">Not enough history for a trend yet. '
            "Each <code>complyos digest</code> run records a snapshot.</p>"
        )

    peak = max(max(points), 1)
    inner_w = CHART_WIDTH - 2 * CHART_PAD
    inner_h = CHART_HEIGHT - 2 * CHART_PAD
    step = inner_w / (len(points) - 1)
    coords = [
        (
            round(CHART_PAD + i * step, 1),
            round(CHART_PAD + inner_h * (1 - value / peak), 1),
        )
        for i, value in enumerate(points)
    ]
    polyline = " ".join(f"{x},{y}" for x, y in coords)
    dots = "".join(
        f'<circle cx="{x}" cy="{y}" r="3" fill="var(--accent)" />' for x, y in coords
    )
    label = (
        f"Open course gaps over the last {len(points)} audits: "
        f"{', '.join(str(p) for p in points)}"
    )
    return (
        f'<svg viewBox="0 0 {CHART_WIDTH} {CHART_HEIGHT}" role="img" '
        f'aria-label="{_esc(label)}" width="100%" '
        f'preserveAspectRatio="xMidYMid meet">'
        f'<polyline points="{polyline}" fill="none" '
        f'stroke="var(--accent)" stroke-width="2" />'
        f"{dots}</svg>"
        f'<p class="empty">{_esc(label)}</p>'
    )


def generate_dashboard(
    report: AuditReport,
    history: list[dict[str, Any]] | None = None,
    output_path: str = "dashboard.html",
) -> str:
    """Render the dashboard HTML file and return its path."""
    severity_counts = report.gaps_by_severity
    # Snapshot history counts flattened (user, course) pairs — use the
    # same unit for the current trend point or the chart lies.
    current_course_gaps = sum(len(gap.missing_courses) for gap in report.details)
    gap_rows = "\n".join(_gap_row(gap) for gap in report.details)
    if not gap_rows:
        gap_rows = '<tr><td colspan="5">No gaps found — fully compliant.</td></tr>'

    html_out = DASHBOARD_TEMPLATE.format(
        generated_at=_esc(report.generated_at.isoformat()),
        scope=_esc(report.scope or "all"),
        total_users=report.total_users_audited,
        gaps_found=report.gaps_found,
        critical_count=severity_counts.get("critical", 0),
        high_count=severity_counts.get("high", 0),
        medium_count=severity_counts.get("medium", 0),
        low_count=severity_counts.get("low", 0),
        trend_section=_trend_section(history or [], current_course_gaps),
        dept_bars=_dept_bars(report.gaps_by_department),
        gap_rows=gap_rows,
        evidence_hash=_esc(report.evidence_hash),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    return output_path
