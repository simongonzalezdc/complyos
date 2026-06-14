"""Generic inbound webhook intake with tenant-scoped receipt persistence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from complyos.core.repository import LocalRepository
from complyos.notification.signing import verify_signature
from complyos.services.context import (
    PERM_NOTIFICATIONS_MANAGE,
    ActorContext,
    require_permission,
)
from complyos.services.notifications import _payload_hash, _redact_payload

# Replay window: a captured, validly-signed request older/newer than this is
# rejected even though its HMAC still matches the timestamp it was signed with.
INBOUND_SIGNATURE_MAX_AGE_SECONDS = 300


class InboundWebhookSignatureError(PermissionError):
    """Raised when a configured inbound webhook secret does not validate."""

    code = "inbound_signature_invalid"


class InboundHookService:
    """Record generic inbound hook events without provider-specific parsing."""

    def __init__(self, repository: LocalRepository) -> None:
        self.repository = repository

    def record(
        self,
        context: ActorContext,
        *,
        source: str,
        body: bytes,
        headers: Mapping[str, str],
        signing_secret: str | None = None,
        require_signature: bool = True,
    ) -> dict[str, Any]:
        """Validate optional HMAC signature, redact payload, and store receipt."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        normalized_source = _normalize_source(source)
        signature_valid = _verify_signature(
            signing_secret,
            headers=headers,
            body=body,
            require_signature=require_signature,
        )
        payload = _parse_body(body)
        event_type = str(payload.get("event_type") or payload.get("type") or "inbound.received")
        object_type = str(payload.get("object_type") or "inbound_event")
        object_id = payload.get("object_id") or payload.get("id")
        redacted_payload = _redact_payload(payload)
        stored = self.repository.save_inbound_webhook_event(
            tenant_id=context.tenant_id,
            source=normalized_source,
            event_type=event_type,
            object_type=object_type,
            object_id=str(object_id) if object_id is not None else None,
            payload=redacted_payload,
            payload_hash=_payload_hash(redacted_payload),
            signature_valid=signature_valid,
            status="received",
            header_metadata=_safe_header_metadata(headers),
            received_by=context.actor_id,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="inbound_webhook.received",
            object_type=object_type,
            object_id=stored["object_id"],
            result="received",
            request_id=context.request_id,
            metadata={
                "source": normalized_source,
                "event_type": event_type,
                "payload_hash": stored["payload_hash"],
                "signature_valid": signature_valid,
            },
        )
        return stored

    def list_receipts(
        self,
        context: ActorContext,
        *,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List received inbound hook receipts for the current tenant."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        return self.repository.list_inbound_webhook_events(
            tenant_id=context.tenant_id,
            source=_normalize_source(source) if source else None,
            limit=limit,
        )


def _verify_signature(
    signing_secret: str | None,
    *,
    headers: Mapping[str, str],
    body: bytes,
    require_signature: bool = True,
) -> bool:
    if not signing_secret:
        # Fail closed by default: a missing secret must not silently downgrade
        # this PII-ingestion surface to "accept anything". Callers opt into
        # unsigned acceptance explicitly (e.g. trusted local-only use).
        if require_signature:
            raise InboundWebhookSignatureError(
                "inbound webhook signing secret is not configured"
            )
        return False
    timestamp = headers.get("x-complyos-timestamp") or headers.get("X-ComplyOS-Timestamp")
    signature = headers.get("x-complyos-signature") or headers.get("X-ComplyOS-Signature")
    if not timestamp or not signature:
        raise InboundWebhookSignatureError("missing inbound webhook signature")
    _require_fresh_timestamp(timestamp)
    if not verify_signature(signing_secret, timestamp=timestamp, body=body, signature=signature):
        raise InboundWebhookSignatureError("invalid inbound webhook signature")
    return True


def _require_fresh_timestamp(timestamp: str) -> None:
    """Reject signed requests outside the replay window (anti-replay defense)."""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise InboundWebhookSignatureError("invalid inbound webhook timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age_seconds = abs((datetime.now(UTC) - parsed).total_seconds())
    if age_seconds > INBOUND_SIGNATURE_MAX_AGE_SECONDS:
        raise InboundWebhookSignatureError("inbound webhook timestamp outside tolerance window")


def _parse_body(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw_body_hash": hashlib.sha256(body).hexdigest()}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}


def _safe_header_metadata(headers: Mapping[str, str]) -> dict[str, Any]:
    return {
        "content_type": headers.get("content-type") or headers.get("Content-Type"),
        "user_agent": headers.get("user-agent") or headers.get("User-Agent"),
        "signature_present": bool(
            headers.get("x-complyos-signature") or headers.get("X-ComplyOS-Signature")
        ),
    }


def _normalize_source(source: str) -> str:
    normalized = source.strip().lower()
    if not normalized:
        raise ValueError("inbound hook source is required")
    return normalized
