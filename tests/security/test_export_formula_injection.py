"""Adversarial export tests: spreadsheet formula + HTML injection neutralization.

Plan §13.2 (export injection / formula injection). The HTML report interpolates
learner/source-derived fields (names, department, course titles). A field that
begins with ``=``, ``+``, ``-``, ``@`` or a leading tab/CR must be neutralized so
it cannot execute when the report is opened or pasted into Excel/Sheets, and any
markup it contains must be HTML-escaped so it cannot inject script into the page.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from complyos.core.report_exporter import render_html
from complyos.models.domain import AuditReport, ComplianceGap, Course, User

# A leading "=2+5+cmd|' /C calc'!A0" is the canonical CSV/Sheets formula-injection
# payload; "@SUM" and a leading-tab variant cover the other dangerous prefixes.
FORMULA_PAYLOAD = "=2+5+cmd|' /C calc'!A0"
HTML_PAYLOAD = "<script>alert(1)</script>"
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _user(first: str, last: str, department: str) -> User:
    return User(
        id="u-attacker",
        employee_id="E-1",
        email="a@example.com",
        first_name=first,
        last_name=last,
        department=department,
        region="US",
        hire_date=datetime(2020, 1, 1, tzinfo=UTC).date(),
    )


def _report(*, first: str, last: str, department: str, course_title: str) -> AuditReport:
    gap = ComplianceGap(
        user=_user(first, last, department),
        missing_courses=[Course(id="c1", code="C1", title=course_title)],
        days_overdue=3,
        severity="high",
    )
    return AuditReport(
        generated_at=datetime(2026, 6, 13, tzinfo=UTC),
        scope="all",
        total_users_audited=1,
        gaps_found=1,
        gaps_by_severity={"high": 1},
        gaps_by_department={department: 1},
        top_missing_courses=[("C1", 1)],
        evidence_hash="deadbeef",
        details=[gap],
    )


def test_render_html_neutralizes_formula_in_learner_fields() -> None:
    report = _report(
        first=FORMULA_PAYLOAD,
        last="Doe",
        department="@SUM(1+1)",
        course_title="-cmd",
    )

    html = render_html(report)

    # The raw formula payload must never appear verbatim: it is quote-prefixed
    # (formula-neutralized) and HTML-escaped, so the live "=" never opens a cell.
    assert FORMULA_PAYLOAD not in html
    # The neutralized form is present: a leading apostrophe before the (escaped) "=".
    assert "&#x27;=2+5" in html
    # The department field led with "@" — it too is quote-prefixed.
    assert "&#x27;@SUM(1+1)" in html


def test_render_html_escapes_markup_so_it_cannot_inject_script() -> None:
    report = _report(
        first="Mallory",
        last=HTML_PAYLOAD,
        department="Eng",
        course_title=HTML_PAYLOAD,
    )

    html = render_html(report)

    # No live <script> tag is emitted; it is HTML-entity-escaped instead.
    assert HTML_PAYLOAD not in html
    assert "&lt;script&gt;" in html


def test_no_user_derived_cell_starts_with_a_formula_prefix() -> None:
    """End-to-end guard: every learner/source cell that lands in the report is
    neutralized regardless of which dangerous prefix the attacker chose."""
    for prefix in DANGEROUS_PREFIXES:
        payload = f"{prefix}HYPERLINK(0)"
        report = _report(
            first=payload,
            last=payload,
            department=payload,
            course_title=payload,
        )

        html = render_html(report)

        # The payload must never sit at the start of a table cell with its
        # dangerous prefix intact: a quote-prefixed cell (``<td>'=...``) is safe,
        # a raw one (``<td>=...``) is not. Assert no raw dangerous cell exists.
        assert f"<td>{prefix}" not in html, f"prefix {prefix!r} passed through unescaped"
        # And the neutralized, quote-prefixed form is what actually lands.
        assert "<td>&#x27;" in html or f"<td>'{prefix}" in html


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
