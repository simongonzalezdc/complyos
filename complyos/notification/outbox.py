"""Generic webhook sender for notification outbox deliveries."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

import httpx


class WebhookEventSender:
    """Send outbox events to configured webhook URLs with optional HMAC signing."""

    def __init__(
        self,
        *,
        channel_urls: dict[str, str],
        signing_secret: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.channel_urls = {key.lower(): value for key, value in channel_urls.items() if value}
        self.signing_secret = signing_secret
        self.timeout = timeout

    async def send_delivery(self, delivery: dict[str, Any]) -> dict[str, Any]:
        """Send one delivery row; return a status payload for service marking."""
        channel = str(delivery["channel"]).lower()
        url = self.channel_urls.get(channel)
        if not url:
            return {
                "sent": False,
                "skipped": True,
                "channel": channel,
                "error": f"No webhook URL configured for channel: {channel}",
            }

        event = delivery.get("event")
        if not isinstance(event, dict):
            raise ValueError("notification delivery is missing event payload")
        body = _event_body(event)
        timestamp = datetime.now(UTC).isoformat()
        headers = {
            "Content-Type": "application/json",
            "X-ComplyOS-Event-Id": str(event["id"]),
            "X-ComplyOS-Event-Type": str(event["event_type"]),
            "X-ComplyOS-Timestamp": timestamp,
            "Idempotency-Key": str(delivery["id"]),
        }
        if self.signing_secret:
            headers["X-ComplyOS-Signature"] = _signature(
                self.signing_secret,
                timestamp=timestamp,
                body=body,
            )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, content=body, headers=headers)
            response.raise_for_status()
        return {
            "sent": True,
            "skipped": False,
            "channel": channel,
            "status_code": response.status_code,
        }


def _event_body(event: dict[str, Any]) -> bytes:
    payload = {
        "id": event["id"],
        "type": event["event_type"],
        "tenant_id": event["tenant_id"],
        "source": event.get("source", "complyos"),
        "object_type": event["object_type"],
        "object_id": event.get("object_id"),
        "payload": event.get("payload") or {},
        "payload_hash": event["payload_hash"],
    }
    return json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")


def _signature(secret: str, *, timestamp: str, body: bytes) -> str:
    signed = timestamp.encode("utf-8") + b"." + body
    digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"sha256={digest}"
