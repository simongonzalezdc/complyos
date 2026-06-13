"""Service-layer notification outbox controls."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_NOTIFICATIONS_MANAGE,
    ActorContext,
    require_permission,
)

VALID_DELIVERY_STATUSES = frozenset({"pending", "sent", "failed", "skipped", "dead_letter"})
SENSITIVE_PAYLOAD_KEY_PARTS = ("secret", "password", "token", "webhook", "api_key", "apikey")


class NotificationOutboxService:
    """Create and drain auditable notification events without inline network coupling."""

    def __init__(self, repository: LocalRepository) -> None:
        self.repository = repository

    def enqueue_event(
        self,
        context: ActorContext,
        *,
        event_type: str,
        object_type: str,
        object_id: str | None,
        payload: dict[str, Any],
        channels: list[str],
        source: str = "complyos",
    ) -> dict[str, Any]:
        """Persist one event plus pending per-channel delivery rows."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        normalized_channels = _normalize_channels(channels)
        preferences = self.repository.list_notification_preferences(tenant_id=context.tenant_id)
        enabled_channels = [
            channel
            for channel in normalized_channels
            if _channel_enabled(preferences, channel=channel, event_type=event_type)
        ]
        redacted_payload = _redact_payload(payload)
        payload_hash = _payload_hash(redacted_payload)
        event = self.repository.save_notification_event(
            tenant_id=context.tenant_id,
            event_type=event_type,
            source=source,
            object_type=object_type,
            object_id=object_id,
            payload=redacted_payload,
            payload_hash=payload_hash,
            channels=enabled_channels,
            created_by=context.actor_id,
            status="queued" if enabled_channels else "suppressed",
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="notification.event.enqueue",
            object_type=object_type,
            object_id=object_id,
            result="queued",
            request_id=context.request_id,
            metadata={
                "event_type": event_type,
                "channels": normalized_channels,
                "enabled_channels": enabled_channels,
                "suppressed_channels": [
                    channel for channel in normalized_channels if channel not in enabled_channels
                ],
                "payload_hash": payload_hash,
            },
        )
        return event

    def set_preference(
        self,
        context: ActorContext,
        *,
        channel: str,
        event_type: str = "*",
        enabled: bool,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Set an event/channel preference or kill switch for the current tenant."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        normalized_channel = _normalize_selector(channel, field="channel")
        normalized_event_type = _normalize_selector(event_type, field="event_type")
        preference = self.repository.save_notification_preference(
            tenant_id=context.tenant_id,
            channel=normalized_channel,
            event_type=normalized_event_type,
            enabled=enabled,
            reason=reason,
            updated_by=context.actor_id,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="notification.preference.set",
            object_type="notification_preference",
            object_id=str(preference["id"]),
            result="enabled" if enabled else "disabled",
            request_id=context.request_id,
            metadata={
                "channel": normalized_channel,
                "event_type": normalized_event_type,
                "reason": reason,
            },
        )
        return preference

    def list_preferences(self, context: ActorContext) -> list[dict[str, Any]]:
        """List notification preferences for the current tenant."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        return self.repository.list_notification_preferences(tenant_id=context.tenant_id)

    def list_pending_deliveries(
        self,
        context: ActorContext,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List pending deliveries for the current tenant."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        return self.repository.list_notification_deliveries(
            tenant_id=context.tenant_id,
            status="pending",
            limit=limit,
        )

    def mark_delivery_sent(
        self,
        context: ActorContext,
        *,
        delivery_id: str,
        response_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mark a delivery as sent and increment attempts."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        delivery = self.repository.mark_notification_delivery(
            tenant_id=context.tenant_id,
            delivery_id=delivery_id,
            status="sent",
            increment_attempts=True,
            response_metadata=response_metadata,
            sent_at=datetime.utcnow(),
        )
        self._log_delivery(context, delivery, result="sent")
        return delivery

    def mark_delivery_skipped(
        self,
        context: ActorContext,
        *,
        delivery_id: str,
        error: str,
    ) -> dict[str, Any]:
        """Mark a delivery skipped because the channel is intentionally unavailable."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        delivery = self.repository.mark_notification_delivery(
            tenant_id=context.tenant_id,
            delivery_id=delivery_id,
            status="skipped",
            increment_attempts=False,
            error=error,
            response_metadata={"skipped": True},
        )
        self._log_delivery(context, delivery, result="skipped")
        return delivery

    def mark_delivery_failed(
        self,
        context: ActorContext,
        *,
        delivery_id: str,
        error: str,
    ) -> dict[str, Any]:
        """Record a failed attempt, leaving room for retry or dead-letter state."""
        require_permission(context, PERM_NOTIFICATIONS_MANAGE)
        current = self._get_pending_delivery(context, delivery_id)
        next_attempt_count = int(current["attempts"]) + 1
        max_attempts = int(current["max_attempts"])
        status = "dead_letter" if next_attempt_count >= max_attempts else "pending"
        delivery = self.repository.mark_notification_delivery(
            tenant_id=context.tenant_id,
            delivery_id=delivery_id,
            status=status,
            increment_attempts=True,
            error=error,
            next_attempt_at=(
                None if status == "dead_letter" else datetime.utcnow() + timedelta(minutes=5)
            ),
            response_metadata={"error": error},
        )
        self._log_delivery(context, delivery, result=status)
        return delivery

    def _get_pending_delivery(self, context: ActorContext, delivery_id: str) -> dict[str, Any]:
        for delivery in self.list_pending_deliveries(context, limit=500):
            if delivery["id"] == delivery_id:
                return delivery
        raise ValueError(f"unknown pending notification delivery: {delivery_id}")

    def _log_delivery(
        self,
        context: ActorContext,
        delivery: dict[str, Any],
        *,
        result: str,
    ) -> None:
        event = delivery.get("event") or {}
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="notification.delivery.update",
            object_type="notification_delivery",
            object_id=str(delivery["id"]),
            result=result,
            request_id=context.request_id,
            metadata={
                "channel": delivery["channel"],
                "event_type": event.get("event_type"),
                "attempts": delivery["attempts"],
            },
        )


def _normalize_channels(channels: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for channel in channels:
        value = channel.strip().lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if not normalized:
        raise ValueError("at least one notification channel is required")
    return normalized


def _normalize_selector(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _channel_enabled(
    preferences: list[dict[str, Any]],
    *,
    channel: str,
    event_type: str,
) -> bool:
    """Return effective preference using exact match before wildcard fallback."""
    normalized_channel = channel.lower()
    normalized_event = event_type.lower()
    matches: list[tuple[int, dict[str, Any]]] = []
    for preference in preferences:
        pref_channel = str(preference["channel"]).lower()
        pref_event = str(preference["event_type"]).lower()
        channel_match = pref_channel in {normalized_channel, "*"}
        event_match = pref_event in {normalized_event, "*"}
        if not channel_match or not event_match:
            continue
        specificity = int(pref_channel == normalized_channel) + int(pref_event == normalized_event)
        matches.append((specificity, preference))
    if not matches:
        return True
    _, most_specific = sorted(matches, key=lambda item: item[0], reverse=True)[0]
    return bool(most_specific["enabled"])


def _redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(part in lowered for part in SENSITIVE_PAYLOAD_KEY_PARTS):
                continue
            redacted[str(key)] = _redact_payload(child)
        return redacted
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    return value


def _payload_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
