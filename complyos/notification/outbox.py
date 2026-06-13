"""Generic email and webhook senders for notification outbox deliveries."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any, Protocol

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


class EmailSender(Protocol):
    async def send_email(
        self,
        to_address: str,
        subject: str,
        body: str,
    ) -> dict[str, Any]:
        """Send one plain-text email."""


class EmailEventSender:
    """Send outbox events through the existing SMTP notification adapter."""

    def __init__(
        self,
        *,
        notification_sender: EmailSender,
        default_recipients: list[str],
    ) -> None:
        self.notification_sender = notification_sender
        self.default_recipients = [
            recipient.strip() for recipient in default_recipients if recipient.strip()
        ]

    async def send_delivery(self, delivery: dict[str, Any]) -> dict[str, Any]:
        channel = str(delivery["channel"]).lower()
        if channel != "email":
            return {
                "sent": False,
                "skipped": True,
                "channel": channel,
                "error": f"Email sender cannot handle channel: {channel}",
            }

        event = delivery.get("event")
        if not isinstance(event, dict):
            raise ValueError("notification delivery is missing event payload")
        payload = _event_payload(event)
        recipients = _email_recipients(payload, self.default_recipients)
        if not recipients:
            return {
                "sent": False,
                "skipped": True,
                "channel": "email",
                "error": "No email recipients configured for notification delivery",
            }

        subject = str(
            payload.get("email_subject")
            or payload.get("subject")
            or f"ComplyOS event: {event['event_type']}"
        )
        body = _email_body(event)
        errors: list[str] = []
        for recipient in recipients:
            result = await self.notification_sender.send_email(
                to_address=recipient,
                subject=subject,
                body=body,
            )
            if not result.get("sent"):
                errors.append(f"{recipient}: {result.get('error', 'send failed')}")

        if errors:
            return {
                "sent": False,
                "skipped": False,
                "channel": "email",
                "error": "; ".join(errors),
                "recipient_count": len(recipients),
            }
        return {
            "sent": True,
            "skipped": False,
            "channel": "email",
            "recipient_count": len(recipients),
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


def _email_recipients(payload: dict[str, Any], default_recipients: list[str]) -> list[str]:
    raw = payload.get("email_to") or payload.get("recipients") or payload.get("recipient")
    recipients: list[str] = []
    if isinstance(raw, str):
        recipients.extend(item.strip() for item in raw.split(",") if item.strip())
    elif isinstance(raw, list):
        recipients.extend(str(item).strip() for item in raw if str(item).strip())
    else:
        recipients.extend(default_recipients)
    seen: set[str] = set()
    unique: list[str] = []
    for recipient in recipients:
        lowered = recipient.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique.append(recipient)
    return unique


def _email_body(event: dict[str, Any]) -> str:
    payload = _event_payload(event)
    if payload.get("email_body"):
        return str(payload["email_body"])
    lines = [
        f"Event: {event['event_type']}",
        f"Tenant: {event['tenant_id']}",
        f"Object: {event['object_type']} / {event.get('object_id') or 'n/a'}",
    ]
    if payload.get("summary"):
        lines.extend(["", str(payload["summary"])])
    lines.extend(
        [
            "",
            "Payload:",
            json.dumps(payload, indent=2, sort_keys=True, default=str),
        ]
    )
    return "\n".join(lines)


def _event_payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, dict) else {}
