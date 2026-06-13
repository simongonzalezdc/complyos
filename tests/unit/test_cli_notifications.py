from __future__ import annotations

import json

import respx
from httpx import Response
from typer.testing import CliRunner

from complyos.cli import app
from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.notifications import NotificationOutboxService

runner = CliRunner()


def _seed_event(db_path: str) -> None:
    service = NotificationOutboxService(LocalRepository(db_path))
    service.enqueue_event(
        default_local_context(role="compliance_manager"),
        event_type="source_intel.run.completed",
        object_type="source_intel_run",
        object_id="run-123",
        payload={"proposal_count": 2},
        channels=["webhook"],
    )


def test_notifications_list_and_drain_dry_run(tmp_path) -> None:
    db_path = str(tmp_path / "notifications-cli.db")
    _seed_event(db_path)

    listed = runner.invoke(app, ["notifications", "list", "--db", db_path, "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.output)["pending_count"] == 1

    drained = runner.invoke(app, ["notifications", "drain", "--db", db_path, "--dry-run", "--json"])
    assert drained.exit_code == 0
    payload = json.loads(drained.output)
    assert payload["dry_run"] is True
    assert payload["pending_count"] == 1
    assert payload["deliveries"][0]["status"] == "would_send"

    listed_again = runner.invoke(app, ["notifications", "list", "--db", db_path, "--json"])
    assert json.loads(listed_again.output)["pending_count"] == 1


@respx.mock
def test_notifications_drain_send_marks_delivery_sent(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "notifications-send.db")
    _seed_event(db_path)
    monkeypatch.setenv("COMPLYOS_WEBHOOK_URL", "https://hooks.customer.test/complyos")
    monkeypatch.setenv("COMPLYOS_WEBHOOK_SECRET", "unit-test-secret")
    respx.post("https://hooks.customer.test/complyos").mock(return_value=Response(202))

    drained = runner.invoke(app, ["notifications", "drain", "--db", db_path, "--send", "--json"])

    assert drained.exit_code == 0
    payload = json.loads(drained.output)
    assert payload["dry_run"] is False
    assert payload["deliveries"][0]["status"] == "sent"

    listed = runner.invoke(app, ["notifications", "list", "--db", db_path, "--json"])
    assert json.loads(listed.output)["pending_count"] == 0
