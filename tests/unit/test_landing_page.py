"""Static contract tests for the ComplyOS landing page."""

from __future__ import annotations

import re
from pathlib import Path

LANDING_PAGE = Path("docs/index.html")


def _page() -> str:
    return LANDING_PAGE.read_text(encoding="utf-8")


def test_landing_page_exists_with_core_positioning() -> None:
    assert LANDING_PAGE.exists()

    html = _page()

    required_copy = [
        "ComplyOS",
        "The audit trail between HRIS, LMS, CSVs, and the people asking for proof.",
        "One core, two tracks",
        "The latest work turned the app into a control plane.",
        "Workforce compliance",
        "Campus readiness",
        "Bring your LMS exports today. Connect deeply tomorrow.",
        "CLI/API/MCP",
        "DSR + hold",
        "readiness_only",
    ]

    for phrase in required_copy:
        assert phrase in html


def test_landing_page_names_the_target_connectors() -> None:
    html = _page()

    required_systems = [
        "CSV export",
        "Canvas",
        "Moodle",
        "Blackboard",
        "D2L Brightspace",
        "Workday",
        "SAP SuccessFactors",
        "Cornerstone OnDemand",
    ]

    for system in required_systems:
        assert system in html


def test_landing_page_meets_tastecheck_guardrails() -> None:
    html = _page()
    lower_html = html.lower()

    forbidden_terms = [
        "elevate",
        "seamless",
        "unleash",
        "next-gen",
        "john doe",
        "sarah chan",
        "acme",
        "inter,",
        "#000000",
        "h-screen",
        "certified",
        "compliant",
    ]

    for term in forbidden_terms:
        assert term not in lower_html

    assert "min-height: 100dvh" in lower_html
    assert "font-family:" in lower_html
    assert '"geist"' in lower_html
    assert "linear-gradient(135deg" not in lower_html
    assert "border-radius: 999px;\n        background: var(--accent-dark)" not in lower_html
    assert "skip-link" in lower_html
    assert ":focus-visible" in lower_html

    # Emoji ranges most likely to appear in AI-generated marketing pages.
    emoji_pattern = re.compile("[\U0001F300-\U0001FAFF]")
    assert emoji_pattern.search(html) is None
