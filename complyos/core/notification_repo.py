"""Notification outbox + inbound-webhook persistence for LocalRepository."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from complyos.core.repository_base import RepositoryBase
from complyos.core.repository_mappers import RepositoryMappers
from complyos.core.time import utc_now
from complyos.models.database import (
    DBAuditSnapshot,
    DBInboundWebhookEvent,
    DBNotificationDelivery,
    DBNotificationEvent,
    DBNotificationPreference,
)


class NotificationRepositoryMixin(RepositoryBase, RepositoryMappers):
    """Notification events, deliveries, preferences, and inbound receipts."""

    # ------------------------------------------------------------------
    # Notification outbox persistence
    # ------------------------------------------------------------------
    def save_notification_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source: str,
        object_type: str,
        object_id: str | None,
        payload: dict[str, Any],
        payload_hash: str,
        channels: list[str],
        created_by: str,
        status: str = "queued",
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        event_id = str(uuid.uuid4())
        timestamp = created_at or utc_now()
        with self._session() as session:
            event = DBNotificationEvent(
                id=event_id,
                tenant_id=tenant_id,
                event_type=event_type,
                source=source,
                object_type=object_type,
                object_id=object_id,
                payload=payload,
                payload_hash=payload_hash,
                status=status,
                created_by=created_by,
                created_at=timestamp,
            )
            session.add(event)
            for channel in channels:
                session.add(
                    DBNotificationDelivery(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        event_id=event_id,
                        channel=channel,
                        destination_ref=channel,
                        status="pending",
                        attempts=0,
                        max_attempts=3,
                        response_metadata={},
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
            session.commit()
            session.refresh(event)
            return self._to_notification_event_dict(event, delivery_count=len(channels))

    def save_notification_preference(
        self,
        *,
        tenant_id: str,
        channel: str,
        event_type: str,
        enabled: bool,
        reason: str | None,
        updated_by: str,
        updated_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = updated_at or utc_now()
        with self._session() as session:
            preference = (
                session.query(DBNotificationPreference)
                .where(
                    DBNotificationPreference.tenant_id == tenant_id,
                    DBNotificationPreference.channel == channel,
                    DBNotificationPreference.event_type == event_type,
                )
                .first()
            )
            if preference is None:
                preference = DBNotificationPreference(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    channel=channel,
                    event_type=event_type,
                    enabled=enabled,
                    reason=reason,
                    updated_by=updated_by,
                    updated_at=timestamp,
                )
                session.add(preference)
            else:
                preference.enabled = enabled
                preference.reason = reason
                preference.updated_by = updated_by
                preference.updated_at = timestamp
            session.commit()
            session.refresh(preference)
            return self._to_notification_preference_dict(preference)

    def list_notification_preferences(self, *, tenant_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(DBNotificationPreference)
                .where(DBNotificationPreference.tenant_id == tenant_id)
                .order_by(
                    DBNotificationPreference.event_type.asc(),
                    DBNotificationPreference.channel.asc(),
                )
                .all()
            )
            return [self._to_notification_preference_dict(row) for row in rows]

    def save_inbound_webhook_event(
        self,
        *,
        tenant_id: str,
        source: str,
        event_type: str,
        object_type: str,
        object_id: str | None,
        payload: dict[str, Any],
        payload_hash: str,
        signature_valid: bool,
        status: str,
        header_metadata: dict[str, Any],
        received_by: str,
        received_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = received_at or utc_now()
        with self._session() as session:
            event = DBInboundWebhookEvent(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                source=source,
                event_type=event_type,
                object_type=object_type,
                object_id=object_id,
                payload=payload,
                payload_hash=payload_hash,
                signature_valid=signature_valid,
                status=status,
                header_metadata=header_metadata,
                received_by=received_by,
                received_at=timestamp,
            )
            session.add(event)
            session.commit()
            session.refresh(event)
            return self._to_inbound_webhook_event_dict(event)

    def list_inbound_webhook_events(
        self,
        *,
        tenant_id: str,
        source: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBInboundWebhookEvent).where(
                DBInboundWebhookEvent.tenant_id == tenant_id
            )
            if source:
                query = query.where(DBInboundWebhookEvent.source == source)
            rows = query.order_by(DBInboundWebhookEvent.received_at.desc()).limit(limit).all()
            return [self._to_inbound_webhook_event_dict(row) for row in rows]

    def list_notification_deliveries(
        self,
        *,
        tenant_id: str,
        status: str | None = "pending",
        limit: int = 50,
        due_at: datetime | None = None,
    ) -> list[dict[str, Any]]:
        with self._session() as session:
            query = session.query(DBNotificationDelivery).where(
                DBNotificationDelivery.tenant_id == tenant_id
            )
            if status:
                query = query.where(DBNotificationDelivery.status == status)
            if due_at is not None:
                # Honor the retry backoff: a delivery that failed and was scheduled
                # for a future retry must not be re-attempted until it is due. Rows
                # never attempted (next_attempt_at IS NULL) are always due.
                query = query.where(
                    DBNotificationDelivery.next_attempt_at.is_(None)
                    | (DBNotificationDelivery.next_attempt_at <= due_at)
                )
            rows = query.order_by(DBNotificationDelivery.created_at.asc()).limit(limit).all()
            deliveries: list[dict[str, Any]] = []
            for row in rows:
                event = session.get(DBNotificationEvent, row.event_id)
                deliveries.append(self._to_notification_delivery_dict(row, event))
            return deliveries

    def get_notification_delivery(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
    ) -> dict[str, Any] | None:
        """Point lookup of one tenant-scoped delivery (avoids a bounded list scan)."""
        with self._session() as session:
            delivery = (
                session.query(DBNotificationDelivery)
                .where(
                    DBNotificationDelivery.tenant_id == tenant_id,
                    DBNotificationDelivery.id == delivery_id,
                )
                .first()
            )
            if delivery is None:
                return None
            event = session.get(DBNotificationEvent, delivery.event_id)
            return self._to_notification_delivery_dict(delivery, event)

    def mark_notification_delivery(
        self,
        *,
        tenant_id: str,
        delivery_id: str,
        status: str,
        increment_attempts: bool,
        response_metadata: dict[str, Any] | None = None,
        error: str | None = None,
        next_attempt_at: datetime | None = None,
        sent_at: datetime | None = None,
    ) -> dict[str, Any]:
        with self._session() as session:
            delivery = (
                session.query(DBNotificationDelivery)
                .where(
                    DBNotificationDelivery.tenant_id == tenant_id,
                    DBNotificationDelivery.id == delivery_id,
                )
                .first()
            )
            if delivery is None:
                raise ValueError(f"unknown notification delivery: {delivery_id}")
            if increment_attempts:
                delivery.attempts += 1
            delivery.status = status
            delivery.response_metadata = response_metadata or {}
            delivery.last_error = error
            delivery.next_attempt_at = next_attempt_at
            delivery.sent_at = sent_at
            delivery.updated_at = utc_now()
            session.commit()
            session.refresh(delivery)
            event = session.get(DBNotificationEvent, delivery.event_id)
            return self._to_notification_delivery_dict(delivery, event)

    @staticmethod
    def _to_snapshot_dict(snapshot: DBAuditSnapshot) -> dict[str, Any]:
        return {
            "id": snapshot.id,
            "generated_at": snapshot.generated_at,
            "scope": snapshot.scope,
            "gaps_found": snapshot.gaps_found,
            "gaps": snapshot.gaps or [],
            "gaps_by_severity": snapshot.gaps_by_severity or {},
            "evidence_hash": snapshot.evidence_hash,
        }

