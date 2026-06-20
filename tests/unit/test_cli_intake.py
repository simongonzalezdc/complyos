"""CLI coverage for the training-intake commands (submit / list / confirm)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_intake_submit_captures_and_drafts(tmp_path) -> None:
    db = str(tmp_path / "intake.db")
    result = runner.invoke(
        app,
        [
            "intake",
            "submit",
            "New regulatory compliance policy training",
            "--requester",
            "ops-lead",
            "--json",
            "--db",
            db,
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["request"]["status"] == "draft"
    # Proposal-only packet: never confirms scope, flags missing info, suggests routing.
    assert payload["packet"]["confirms_scope"] is False
    assert payload["packet"]["requires_human_confirmation"] is True
    assert payload["packet"]["suggested_routing"] == "compliance-training"
    assert "audience" in payload["packet"]["missing_info"]


def test_intake_list_then_confirm(tmp_path) -> None:
    db = str(tmp_path / "intake.db")
    submit = runner.invoke(
        app,
        ["intake", "submit", "Onboarding refresh", "--requester", "hr", "--json", "--db", db],
    )
    assert submit.exit_code == 0, submit.output
    request_id = json.loads(submit.output)["request"]["id"]

    listed = runner.invoke(app, ["intake", "list", "--json", "--db", db])
    assert listed.exit_code == 0, listed.output
    items = json.loads(listed.output)["items"]
    assert any(item["id"] == request_id for item in items)

    confirmed = runner.invoke(
        app,
        ["intake", "confirm", request_id, "--note", "owner approved", "--json", "--db", db],
    )
    assert confirmed.exit_code == 0, confirmed.output
    confirmed_payload = json.loads(confirmed.output)
    assert confirmed_payload["status"] == "confirmed"
    assert confirmed_payload["confirmed_by"]
    assert confirmed_payload["confirmation_note"] == "owner approved"


def test_intake_list_filters_by_status(tmp_path) -> None:
    db = str(tmp_path / "intake.db")
    runner.invoke(app, ["intake", "submit", "Draft ask", "--requester", "a", "--db", db])
    confirmed_submit = runner.invoke(
        app, ["intake", "submit", "To confirm", "--requester", "b", "--json", "--db", db]
    )
    request_id = json.loads(confirmed_submit.output)["request"]["id"]
    runner.invoke(app, ["intake", "confirm", request_id, "--db", db])

    drafts = runner.invoke(app, ["intake", "list", "--status", "draft", "--json", "--db", db])
    titles = [item["title"] for item in json.loads(drafts.output)["items"]]
    assert titles == ["Draft ask"]
