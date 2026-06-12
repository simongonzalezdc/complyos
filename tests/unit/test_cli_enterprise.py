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


def test_evidence_cli_list_is_tenant_scoped(tmp_path) -> None:
    from complyos.core.repository import LocalRepository

    db_path = tmp_path / "cli-evidence-tenant.db"
    repo = LocalRepository(str(db_path))
    repo.append_evidence_entry(
        tenant_id="tenant-a",
        query_type="audit",
        query_params={"tenant_id": "tenant-a"},
        raw_data_hash="raw-a",
        transformation_steps=["hash"],
        output_hash="tenant-a-hash",
        output_summary="tenant a evidence",
    )
    repo.append_evidence_entry(
        tenant_id="tenant-b",
        query_type="audit",
        query_params={"tenant_id": "tenant-b"},
        raw_data_hash="raw-b",
        transformation_steps=["hash"],
        output_hash="tenant-b-hash",
        output_summary="tenant b evidence",
    )

    result = runner.invoke(
        app,
        [
            "evidence",
            "list",
            "--tenant",
            "tenant-a",
            "--db",
            str(db_path),
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert {item["output_hash"] for item in json.loads(result.output)["items"]} == {
        "tenant-a-hash"
    }


def test_admin_roles_json() -> None:
    result = runner.invoke(app, ["admin", "roles", "--json"])

    assert result.exit_code == 0
    assert "owner" in json.loads(result.output)


def test_security_evidence_cli_json(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "security",
            "evidence",
            "--period",
            "2026-Q2",
            "--db",
            str(tmp_path / "security-cli.db"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["posture"] == "readiness_only"
    assert any(control["control_id"] == "CC6.1" for control in data["controls"])


def test_governance_packet_cli_json(tmp_path) -> None:
    result = runner.invoke(
        app,
        [
            "governance",
            "packet",
            "--lane",
            "campus",
            "--db",
            str(tmp_path / "governance-cli.db"),
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["posture"] == "readiness_only"
    assert any(area["area_id"] == "school-vendor-privacy-accessibility" for area in data["areas"])


def test_privacy_cli_request_retention_and_legal_hold_json(tmp_path) -> None:
    db_path = tmp_path / "privacy-cli.db"

    request = runner.invoke(
        app,
        [
            "privacy",
            "request",
            "u-privacy",
            "--type",
            "access",
            "--region",
            "US-CA",
            "--db",
            str(db_path),
            "--json",
        ],
    )
    assert request.exit_code == 0
    request_data = json.loads(request.output)
    assert request_data["subject_id"] == "u-privacy"
    assert request_data["status"] == "PENDING_CONTROLLER_APPROVAL"

    approved = runner.invoke(
        app,
        [
            "privacy",
            "approve",
            request_data["request_id"],
            "--note",
            "controller approved",
            "--db",
            str(db_path),
            "--json",
        ],
    )
    assert approved.exit_code == 0
    assert json.loads(approved.output)["status"] == "APPROVED"

    retention = runner.invoke(
        app,
        [
            "privacy",
            "retention",
            "configure",
            "--raw-import-days",
            "30",
            "--evidence-days",
            "2555",
            "--action-log-days",
            "2555",
            "--ai-proposal-days",
            "180",
            "--privacy-request-days",
            "365",
            "--db",
            str(db_path),
            "--json",
        ],
    )
    assert retention.exit_code == 0
    assert json.loads(retention.output)["policy"]["raw_import_days"] == 30

    retention_run = runner.invoke(
        app,
        [
            "privacy",
            "retention",
            "run",
            "--dry-run",
            "--db",
            str(db_path),
            "--json",
        ],
    )
    assert retention_run.exit_code == 0
    assert json.loads(retention_run.output)["dry_run"] is True

    hold = runner.invoke(
        app,
        [
            "privacy",
            "legal-hold",
            "u-privacy",
            "--scope",
            "subject",
            "--reason",
            "investigation",
            "--db",
            str(db_path),
            "--json",
        ],
    )
    assert hold.exit_code == 0
    assert json.loads(hold.output)["status"] == "ACTIVE"
