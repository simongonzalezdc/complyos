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


def _seed_event(
    db_path: str,
    *,
    channels: list[str] | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    service = NotificationOutboxService(LocalRepository(db_path))
    service.enqueue_event(
        default_local_context(role="compliance_manager"),
        event_type="source_intel.run.completed",
        object_type="source_intel_run",
        object_id="run-123",
        payload=payload or {"proposal_count": 2},
        channels=channels or ["webhook"],
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


def test_notifications_drain_routes_email_delivery(tmp_path, monkeypatch) -> None:
    db_path = str(tmp_path / "notifications-email.db")
    _seed_event(
        db_path,
        channels=["email"],
        payload={
            "email_to": ["ops@example.com"],
            "email_subject": "Run complete",
            "summary": "Scheduled source intelligence finished.",
        },
    )

    class FakeEmailOutboxSender:
        async def send_delivery(self, delivery: dict[str, object]) -> dict[str, object]:
            assert delivery["channel"] == "email"
            return {
                "sent": True,
                "skipped": False,
                "channel": "email",
                "recipient_count": 1,
            }

    monkeypatch.setattr(
        "complyos.cli._get_email_outbox_sender",
        lambda: FakeEmailOutboxSender(),
        raising=False,
    )

    drained = runner.invoke(app, ["notifications", "drain", "--db", db_path, "--send", "--json"])

    assert drained.exit_code == 0
    payload = json.loads(drained.output)
    assert payload["deliveries"][0]["status"] == "sent"


def test_notifications_preference_cli_sets_and_lists_kill_switch(tmp_path) -> None:
    db_path = str(tmp_path / "notifications-prefs-cli.db")

    set_result = runner.invoke(
        app,
        [
            "notifications",
            "preference-set",
            "--db",
            db_path,
            "--channel",
            "email",
            "--event-type",
            "audit.completed",
            "--disabled",
            "--reason",
            "quiet hours",
            "--json",
        ],
    )
    assert set_result.exit_code == 0
    assert json.loads(set_result.output)["enabled"] is False

    list_result = runner.invoke(
        app,
        ["notifications", "preferences", "--db", db_path, "--json"],
    )
    assert list_result.exit_code == 0
    payload = json.loads(list_result.output)
    assert payload["preferences"][0]["channel"] == "email"
    assert payload["preferences"][0]["event_type"] == "audit.completed"
