"""Tests for generic notification outbox webhook delivery."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from complyos.notification.outbox import EmailEventSender, WebhookEventSender
from complyos.notification.signing import sign_payload, verify_signature


def _delivery(channel: str = "webhook") -> dict[str, object]:
    return {
        "id": "delivery-1",
        "channel": channel,
        "event": {
            "id": "event-1",
            "event_type": "source_intel.proposals_waiting",
            "tenant_id": "tenant-a",
            "object_type": "source_intel_run",
            "object_id": "run-123",
            "payload": {"proposal_count": 2},
            "payload_hash": "abc123",
        },
    }


@pytest.mark.asyncio
@respx.mock
async def test_webhook_event_sender_posts_signed_payload_without_exposing_secret() -> None:
    route = respx.post("https://hooks.customer.test/complyos").mock(
        return_value=Response(202, text="accepted")
    )
    sender = WebhookEventSender(
        channel_urls={"webhook": "https://hooks.customer.test/complyos"},
        signing_secret="top-secret",
    )

    result = await sender.send_delivery(_delivery())

    assert result["sent"] is True
    assert result["channel"] == "webhook"
    request = route.calls[0].request
    body = request.read()
    timestamp = request.headers["X-ComplyOS-Timestamp"]
    signature = request.headers["X-ComplyOS-Signature"]
    assert request.headers["X-ComplyOS-Event-Id"] == "event-1"
    assert request.headers["X-ComplyOS-Event-Type"] == "source_intel.proposals_waiting"
    assert b"top-secret" not in body
    assert b'"proposal_count":2' in body

    # Verify the ACTUAL digest, not just the prefix: the receiving end must be
    # able to recompute and validate the signature over the exact signed bytes.
    expected = sign_payload("top-secret", timestamp=timestamp, body=body)
    assert signature == expected
    assert verify_signature("top-secret", timestamp=timestamp, body=body, signature=signature)
    # A tampered body must NOT verify against the captured signature.
    assert not verify_signature(
        "top-secret", timestamp=timestamp, body=body + b"x", signature=signature
    )
    # A wrong secret must NOT verify (guards against signing with unexpected bytes).
    assert not verify_signature(
        "wrong-secret", timestamp=timestamp, body=body, signature=signature
    )


@pytest.mark.asyncio
async def test_webhook_event_sender_skips_missing_channel_url() -> None:
    sender = WebhookEventSender(channel_urls={})

    result = await sender.send_delivery(_delivery("slack"))

    assert result == {
        "sent": False,
        "skipped": True,
        "channel": "slack",
        "error": "No webhook URL configured for channel: slack",
    }


class FakeEmailSender:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def send_email(self, to_address: str, subject: str, body: str) -> dict[str, object]:
        self.calls.append({"to": to_address, "subject": subject, "body": body})
        return {"sent": True}


@pytest.mark.asyncio
async def test_email_event_sender_uses_payload_recipients_and_subject() -> None:
    sender = FakeEmailSender()
    delivery = _delivery("email")
    assert isinstance(delivery["event"], dict)
    delivery["event"]["payload"] = {
        "email_to": ["ops@example.com", "legal@example.com"],
        "email_subject": "Privacy request waiting",
        "summary": "Controller approval needed",
    }

    result = await EmailEventSender(
        notification_sender=sender,
        default_recipients=[],
    ).send_delivery(delivery)

    assert result["sent"] is True
    assert result["channel"] == "email"
    assert result["recipient_count"] == 2
    assert [call["to"] for call in sender.calls] == ["ops@example.com", "legal@example.com"]
    assert sender.calls[0]["subject"] == "Privacy request waiting"
    assert "Controller approval needed" in sender.calls[0]["body"]


@pytest.mark.asyncio
async def test_email_event_sender_skips_when_no_recipients_are_configured() -> None:
    result = await EmailEventSender(
        notification_sender=FakeEmailSender(),
        default_recipients=[],
    ).send_delivery(_delivery("email"))

    assert result == {
        "sent": False,
        "skipped": True,
        "channel": "email",
        "error": "No email recipients configured for notification delivery",
    }
