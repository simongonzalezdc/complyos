"""CLI tests for enterprise remediation commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()
CSV_TEXT = "user_id,course_id,status,source_record_id\nu1,c1,completed,sr1\n"


def test_readiness_command_json(tmp_path) -> None:
    result = runner.invoke(app, ["readiness", "--db", str(tmp_path / "ready.db"), "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "readiness-only" in data["posture"]


def test_import_preview_promote_and_evidence_json(tmp_path) -> None:
    csv_path = tmp_path / "rows.csv"
    db_path = tmp_path / "cli.db"
    csv_path.write_text(CSV_TEXT, encoding="utf-8")

    preview = runner.invoke(
        app,
        ["import", "preview", str(csv_path), "--db", str(db_path), "--json"],
    )
    assert preview.exit_code == 0
    batch_id = json.loads(preview.output)["batch_id"]

    promoted = runner.invoke(
        app,
        ["import", "promote", batch_id, "--db", str(db_path), "--json"],
    )
    assert promoted.exit_code == 0
    assert json.loads(promoted.output)["status"] == "PROMOTED"

    evidence = runner.invoke(app, ["evidence", "list", "--db", str(db_path), "--json"])
    assert evidence.exit_code == 0
    assert json.loads(evidence.output)["items"][0]["query_type"] == "import.promote"


def test_admin_roles_json() -> None:
    result = runner.invoke(app, ["admin", "roles", "--json"])

    assert result.exit_code == 0
    assert "owner" in json.loads(result.output)
