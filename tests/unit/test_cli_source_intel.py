from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_source_intel_sources_lists_free_and_blocked_sources() -> None:
    result = runner.invoke(app, ["source-intel", "sources", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    ids = {item["id"] for item in data["sources"]}
    assert {"federal-register", "ecfr-title-29", "osha-web"} <= ids
    federal = next(item for item in data["sources"] if item["id"] == "federal-register")
    assert federal["metadata"]["cost"] == "free"
    assert federal["metadata"]["auth"] == "none"


def test_source_intel_run_fixture_writes_review_queue_without_network(tmp_path: Path) -> None:
    store_path = tmp_path / "reviews.jsonl"

    result = runner.invoke(
        app,
        ["source-intel", "run-fixture", "--store", str(store_path), "--json"],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["snapshot_count"] == 1
    assert data["proposal_count"] == 2
    assert store_path.exists()
    stored_lines = store_path.read_text().strip().splitlines()
    assert len(stored_lines) == 2


def test_source_intel_review_lists_and_decides(tmp_path: Path) -> None:
    store_path = tmp_path / "reviews.jsonl"
    seed = runner.invoke(app, ["source-intel", "run-fixture", "--store", str(store_path), "--json"])
    proposal_id = json.loads(seed.output)["proposal_ids"][0]

    list_result = runner.invoke(
        app, ["source-intel", "review", "--store", str(store_path), "--json"]
    )
    assert list_result.exit_code == 0
    listed = json.loads(list_result.output)
    assert listed["proposals"][0]["approval_state"] == "needs_review"

    decide_result = runner.invoke(
        app,
        [
            "source-intel",
            "review",
            "--store",
            str(store_path),
            "--proposal-id",
            proposal_id,
            "--state",
            "approved_for_brief",
            "--json",
        ],
    )
    assert decide_result.exit_code == 0
    decided = json.loads(decide_result.output)
    assert decided["proposal"]["approval_state"] == "approved_for_brief"


def test_source_intel_run_public_dry_run_lists_free_live_clients() -> None:
    result = runner.invoke(app, ["source-intel", "run-public", "--dry-run", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert data["query"] == "training"
    assert data["source_ids"] == ["federal-register", "ecfr-title-29"]
    assert data["store"] == "source-intel-reviews.jsonl"


def test_source_intel_run_upload_processes_approved_text_without_network(tmp_path: Path) -> None:
    source_file = tmp_path / "approved-guidance.txt"
    source_file.write_text(
        "Research shows managers improve feedback with examples, scenario practice, "
        "and a checklist before one-on-ones.",
        encoding="utf-8",
    )
    store_path = tmp_path / "reviews.jsonl"

    result = runner.invoke(
        app,
        [
            "source-intel",
            "run-upload",
            str(source_file),
            "--store",
            str(store_path),
            "--source-id",
            "approved-feedback-guide",
            "--source-name",
            "Approved feedback guide",
            "--topic",
            "manager feedback",
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["snapshot_count"] == 1
    assert data["proposal_count"] == 1
    assert data["proposal_signal_types"] == ["microlearning_opportunity"]
    assert store_path.exists()


def test_source_intel_cli_can_persist_and_review_db_queue(tmp_path: Path) -> None:
    db_path = tmp_path / "source-intel-cli.db"

    run = runner.invoke(
        app,
        ["source-intel", "run-fixture", "--db", str(db_path), "--json"],
    )

    assert run.exit_code == 0
    run_data = json.loads(run.output)
    assert run_data["db_receipt"]["proposal_count"] == 2

    listed = runner.invoke(app, ["source-intel", "review", "--db", str(db_path), "--json"])
    assert listed.exit_code == 0
    proposals = json.loads(listed.output)["proposals"]
    assert len(proposals) == 2

    decided = runner.invoke(
        app,
        [
            "source-intel",
            "review",
            "--db",
            str(db_path),
            "--proposal-id",
            proposals[0]["id"],
            "--state",
            "approved_for_brief",
            "--json",
        ],
    )
    assert decided.exit_code == 0
    assert json.loads(decided.output)["proposal"]["approval_state"] == "approved_for_brief"


def test_source_intel_cli_schedules_runs_and_exports_packet(tmp_path: Path) -> None:
    db_path = tmp_path / "source-intel-scheduled.db"
    packet_path = tmp_path / "review-packet.json"

    created = runner.invoke(
        app,
        [
            "source-intel",
            "schedule-add",
            "--db",
            str(db_path),
            "--name",
            "daily-training-watch",
            "--query",
            "training",
            "--interval-hours",
            "24",
            "--json",
        ],
    )
    assert created.exit_code == 0
    assert json.loads(created.output)["schedule"]["name"] == "daily-training-watch"

    listed = runner.invoke(app, ["source-intel", "schedule-list", "--db", str(db_path), "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.output)["schedules"][0]["name"] == "daily-training-watch"

    run = runner.invoke(
        app,
        ["source-intel", "run-scheduled", "--db", str(db_path), "--force", "--json"],
    )
    assert run.exit_code == 0
    run_payload = json.loads(run.output)
    assert run_payload["executions"][0]["status"] == "succeeded"
    assert run_payload["executions"][0]["summary"]["proposal_count"] == 2

    exported = runner.invoke(
        app,
        [
            "source-intel",
            "export-packet",
            "--db",
            str(db_path),
            "--output",
            str(packet_path),
            "--json",
        ],
    )
    assert exported.exit_code == 0
    export_payload = json.loads(exported.output)
    assert export_payload["packet"]["proposal_count"] == 2
    assert export_payload["output"] == str(packet_path)
    assert packet_path.exists()
    assert json.loads(packet_path.read_text(encoding="utf-8"))["proposal_count"] == 2
