from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_design_system_commits_to_enterprise_evidence_console() -> None:
    spec = (ROOT / "DESIGN-SYSTEM.md").read_text().lower()

    assert "enterprise evidence console" in spec
    assert "workday" in spec
    assert "cornerstone" in spec
    assert "successfactors" in spec
    assert "canvas" in spec
    assert "bloomberg terminal" in spec
    assert "source → record → rule/source → action → approval → packet" in spec
    assert "no purple gradients" in spec


def test_landing_exposes_learningops_maturity_and_demo_packets() -> None:
    html = (ROOT / "docs" / "index.html").read_text().lower()

    for required in [
        'href="#suite"',
        'href="#demos"',
        'id="suite"',
        'id="demos"',
        "./demos/training-from-scratch.md",
        "./demos/fix-messy-training-ops.md",
        "workday",
        "successfactors",
        "cornerstone",
        "canvas",
        "csv fallback",
        "human approval",
        "illustrative demo entries, not live tenant telemetry",
    ]:
        assert required in html

    maturity_labels = ["live", "contract", "synthetic demo", "roadmap"]
    for label in maturity_labels:
        assert f'<span class="maturity">{label}</span>' in html


def test_landing_keeps_tastecheck_anti_slop_boundaries() -> None:
    html = (ROOT / "docs" / "index.html").read_text().lower()

    forbidden = [
        "linear-gradient(135deg, #6366f1",
        "linear-gradient(135deg, #818cf8",
        "a855f7",
        "floating orb",
        "glassmorphism",
        "✨",
        "🚀",
        "john doe",
        "lorem ipsum",
    ]
    for marker in forbidden:
        assert marker not in html

    # Tags may be pill-shaped; text CTAs must not be.
    assert ".button {" in html
    button_block = html.split(".button {", 1)[1].split("}", 1)[0]
    assert "border-radius: 999" not in button_block
    assert ":focus-visible" in html
    assert "prefers-reduced-motion" in html
