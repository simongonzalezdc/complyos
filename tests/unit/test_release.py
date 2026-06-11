"""Release readiness checks."""

from __future__ import annotations

from pathlib import Path

from complyos.core.release import build_release_checklist


def test_release_checklist_reports_required_operator_artifacts() -> None:
    checklist = build_release_checklist(Path.cwd())

    checks = {item["id"]: item for item in checklist}

    assert checks["license"]["ok"] is True
    assert checks["security_policy"]["ok"] is True
    assert checks["readme"]["ok"] is True
    assert checks["architecture"]["ok"] is True
    assert checks["landing_page"]["ok"] is True
    assert checks["release_checklist"]["ok"] is True


def test_release_checklist_flags_missing_security_policy(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Example\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("BUSL-1.1\n", encoding="utf-8")

    checklist = build_release_checklist(tmp_path)
    checks = {item["id"]: item for item in checklist}

    assert checks["security_policy"]["ok"] is False
    assert "SECURITY.md" in checks["security_policy"]["message"]
