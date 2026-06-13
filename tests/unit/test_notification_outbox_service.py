from __future__ import annotations

import pytest

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.notifications import NotificationOutboxService


def test_notification_outbox_service_enqueues_tenant_scoped_event_and_deliveries(
    tmp_path,
) -> None:
    repo = LocalRepository(str(tmp_path / "notifications.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    event = service.enqueue_event(
        context,
        event_type="source_intel.proposals_waiting",
        object_type="source_intel_run",
        object_id="run-123",
        payload={"proposal_count": 2, "secret": "redacted-before-store"},
        channels=["slack", "teams"],
    )

    assert event["tenant_id"] == "tenant-a"
    assert event["event_type"] == "source_intel.proposals_waiting"
    assert event["payload_hash"]
    assert event["delivery_count"] == 2
    assert "secret" not in event["payload"]

    pending = service.list_pending_deliveries(context)
    assert {delivery["channel"] for delivery in pending} == {"slack", "teams"}
    assert {delivery["status"] for delivery in pending} == {"pending"}
    assert {delivery["event"]["event_type"] for delivery in pending} == {
        "source_intel.proposals_waiting"
    }

    other_context = default_local_context(tenant_id="tenant-b", role="compliance_manager")
    assert service.list_pending_deliveries(other_context) == []

    actions = repo.list_action_logs(tenant_id="tenant-a")
    assert actions[0]["action"] == "notification.event.enqueue"
    assert actions[0]["redacted_metadata"]["event_type"] == "source_intel.proposals_waiting"


def test_notification_outbox_service_marks_delivery_states(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "notifications-states.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")
    service.enqueue_event(
        context,
        event_type="audit.completed",
        object_type="audit_snapshot",
        object_id="snap-1",
        payload={"gaps_found": 3},
        channels=["webhook"],
    )
    delivery = service.list_pending_deliveries(context)[0]

    sent = service.mark_delivery_sent(
        context,
        delivery_id=delivery["id"],
        response_metadata={"status_code": 202},
    )
    assert sent["status"] == "sent"
    assert sent["attempts"] == 1
    assert sent["response_metadata"]["status_code"] == 202

    service.enqueue_event(
        context,
        event_type="audit.high_risk_gaps_found",
        object_type="audit_snapshot",
        object_id="snap-2",
        payload={"critical": 1},
        channels=["webhook"],
    )
    failed_delivery = service.list_pending_deliveries(context)[0]
    failed = service.mark_delivery_failed(
        context,
        delivery_id=failed_delivery["id"],
        error="503 Service Unavailable",
    )
    assert failed["status"] == "pending"
    assert failed["attempts"] == 1
    assert failed["last_error"] == "503 Service Unavailable"


def test_failed_delivery_respects_backoff_then_dead_letters_at_max_attempts(tmp_path) -> None:
    """Failed deliveries back off (no hot-loop) and dead-letter at max_attempts."""
    repo = LocalRepository(str(tmp_path / "notifications-deadletter.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")
    service.enqueue_event(
        context,
        event_type="privacy.delete.blocked_by_legal_hold",
        object_type="privacy_request",
        object_id="dsr-1",
        payload={"subject_id": "u-1"},
        channels=["webhook"],
    )
    delivery_id = service.list_pending_deliveries(context)[0]["id"]

    # Attempt 1: still retryable, and a backoff is scheduled.
    first = service.mark_delivery_failed(context, delivery_id=delivery_id, error="503")
    assert first["status"] == "pending"
    assert first["attempts"] == 1
    assert first["next_attempt_at"] is not None

    # Backoff is ENFORCED: a just-failed delivery is not returned for draining
    # until its next_attempt_at elapses (this is the hot-loop regression guard).
    assert service.list_pending_deliveries(context) == []

    # Attempt 2: still pending (2 < max_attempts of 3).
    second = service.mark_delivery_failed(context, delivery_id=delivery_id, error="503")
    assert second["status"] == "pending"
    assert second["attempts"] == 2

    # Attempt 3: hits max_attempts -> dead_letter, and the retry clock is cleared.
    third = service.mark_delivery_failed(context, delivery_id=delivery_id, error="503")
    assert third["status"] == "dead_letter"
    assert third["attempts"] == 3
    assert third["next_attempt_at"] is None

    # A dead-letter result is recorded in the audit action log.
    actions = repo.list_action_logs(tenant_id="tenant-a")
    assert any(item["result"] == "dead_letter" for item in actions)


def test_mark_delivery_failed_raises_for_unknown_delivery(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "notifications-unknown.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    with pytest.raises(ValueError, match="unknown notification delivery"):
        service.mark_delivery_failed(context, delivery_id="does-not-exist", error="boom")


def test_notification_preferences_disable_channel_without_losing_event_audit(
    tmp_path,
) -> None:
    repo = LocalRepository(str(tmp_path / "notification-preferences.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    preference = service.set_preference(
        context,
        channel="slack",
        event_type="privacy.request.created",
        enabled=False,
        reason="privacy events go to email/teams first",
    )
    assert preference["enabled"] is False

    event = service.enqueue_event(
        context,
        event_type="privacy.request.created",
        object_type="privacy_request",
        object_id="dsr-1",
        payload={"subject_id": "u-1"},
        channels=["slack", "teams"],
    )

    assert event["status"] == "queued"
    assert event["delivery_count"] == 1
    assert service.list_preferences(context)[0]["channel"] == "slack"
    pending = service.list_pending_deliveries(context)
    assert {delivery["channel"] for delivery in pending} == {"teams"}


def test_notification_preferences_wildcard_can_suppress_all_deliveries(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "notification-kill-switch.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    service.set_preference(
        context,
        channel="*",
        event_type="*",
        enabled=False,
        reason="tenant-wide notification freeze",
    )

    event = service.enqueue_event(
        context,
        event_type="audit.completed",
        object_type="audit_snapshot",
        object_id="snap-1",
        payload={"gaps_found": 2},
        channels=["email", "webhook"],
    )

    assert event["status"] == "suppressed"
    assert event["delivery_count"] == 0
    assert service.list_pending_deliveries(context) == []
