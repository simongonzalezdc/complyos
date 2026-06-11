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
        "Compliance-grade learning records for workforce and campus teams.",
        "One core, two tracks",
        "Workforce compliance",
        "Campus readiness",
        "Bring your LMS exports today. Connect deeply tomorrow.",
    ]

    for phrase in required_copy:
        assert phrase in html


def test_landing_page_names_the_target_connectors() -> None:
    html = _page()

    required_systems = [
        "Canvas",
        "Moodle",
        "Blackboard",
        "D2L Brightspace",
        "Workday",
        "PeopleSoft",
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
    ]

    for term in forbidden_terms:
        assert term not in lower_html

    assert "min-height: 100dvh" in lower_html
    assert "font-family: \"geist\"" in lower_html
    assert "linear-gradient(135deg" not in lower_html

    # Emoji ranges most likely to appear in AI-generated marketing pages.
    emoji_pattern = re.compile("[\U0001F300-\U0001FAFF]")
    assert emoji_pattern.search(html) is None
