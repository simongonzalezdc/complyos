"""Release readiness checks."""

from __future__ import annotations

from pathlib import Path

import complyos.core.release as release
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


def test_deployment_checklist_covers_source_intel_hardening() -> None:
    assert hasattr(release, "build_deployment_checklist")
    checklist = release.build_deployment_checklist(Path.cwd())
    checks = {item["id"]: item for item in checklist}

    assert checks["source_intel_docs"]["ok"] is True
    assert checks["external_api_list"]["ok"] is True
    assert checks["source_intel_review_ui"]["ok"] is True
    assert checks["source_intel_api_endpoints"]["ok"] is True
    assert checks["migration_strategy"]["ok"] is True
    assert checks["observability_action_logs"]["ok"] is True
    assert checks["notification_outbox"]["ok"] is True
    assert checks["signed_hook_sender"]["ok"] is True
