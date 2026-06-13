"""Tests for generic notification outbox webhook delivery."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from complyos.notification.outbox import WebhookEventSender


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
    assert request.headers["X-ComplyOS-Event-Id"] == "event-1"
    assert request.headers["X-ComplyOS-Event-Type"] == "source_intel.proposals_waiting"
    assert request.headers["X-ComplyOS-Signature"].startswith("sha256=")
    assert b"top-secret" not in body
    assert b'"proposal_count":2' in body


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
