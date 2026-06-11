"""CLI coverage for Phase 4 operator commands."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_release_check_json_reports_ready() -> None:
    result = runner.invoke(app, ["release-check", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ready"] is True
    ids = {item["id"] for item in data["checks"]}
    assert {"license", "security_policy", "release_checklist"} <= ids


def test_run_schedule_once_runs_due_job(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "complyos.yaml"
    db_path = tmp_path / "scheduled.db"
    config.write_text(
        """
schedule:
  jobs:
    - name: daily-all
      interval_hours: 24
""",
        encoding="utf-8",
    )
    monkeypatch.delenv("COMPLYOS_CSV_DIR", raising=False)
    monkeypatch.delenv("WORKDAY_BASE_URL", raising=False)

    result = runner.invoke(app, ["run-schedule", "--config", str(config), "--db", str(db_path)])

    assert result.exit_code == 0
    assert "daily-all" in result.output
    assert "snapshot" in result.output.lower()


def test_serve_dashboard_dry_run_reports_bind_address() -> None:
    result = runner.invoke(
        app,
        ["serve-dashboard", "--host", "127.0.0.1", "--port", "8765", "--dry-run"],
    )

    assert result.exit_code == 0
    assert "127.0.0.1:8765" in result.output
    assert "dry run" in result.output.lower()
