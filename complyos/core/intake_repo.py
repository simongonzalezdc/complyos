"""Training-intake request persistence for LocalRepository.

Backs :class:`complyos.services.intake.IntakeService`. Mirrors the existing
aggregate-mixin shape (source-intel, notifications): a save/get/list trio plus
a status-transition writer, all tenant-scoped. The persisted entity is the
typed :class:`TrainingRequest`; the proposal-only :class:`IntakePacket` is
derived deterministically by the service and not stored.
"""

from __future__ import annotations

from datetime import datetime

from complyos.core.repository_base import RepositoryBase
from complyos.core.repository_mappers import RepositoryMappers
from complyos.models.database import DBIntakeRequest
from complyos.models.domain import IntakeStatus, TrainingRequest


class IntakeRequestRepositoryMixin(RepositoryBase, RepositoryMappers):
    """Persist and query tenant-scoped training intake requests."""

    def save_intake_request(self, request: TrainingRequest) -> None:
        """Insert or replace a captured intake request (tenant carried on row)."""
        with self._session() as session:
            session.merge(
                DBIntakeRequest(
                    id=request.id,
                    tenant_id=request.tenant_id,
                    requester=request.requester,
                    title=request.title,
                    audience=request.audience,
                    priority=request.priority.value if request.priority else None,
                    business_context=request.business_context,
                    constraints=request.constraints,
                    requested_by_date=request.requested_by_date,
                    status=request.status.value,
                    created_by=request.created_by,
                    created_at=request.created_at,
                    confirmed_by=request.confirmed_by,
                    confirmed_at=request.confirmed_at,
                    confirmation_note=request.confirmation_note,
                )
            )
            session.commit()

    def get_intake_request(self, request_id: str) -> TrainingRequest | None:
        """Fetch one request by id (caller checks tenant ownership)."""
        with self._session() as session:
            row = session.get(DBIntakeRequest, request_id)
            if row is None:
                return None
            return self._to_training_request(row)

    def list_intake_requests(
        self,
        *,
        tenant_id: str,
        status: IntakeStatus | None = None,
        limit: int = 100,
    ) -> list[TrainingRequest]:
        """List a tenant's intake requests, newest first, optionally by status."""
        with self._session() as session:
            query = session.query(DBIntakeRequest).where(
                DBIntakeRequest.tenant_id == tenant_id
            )
            if status is not None:
                query = query.where(DBIntakeRequest.status == status.value)
            rows = (
                query.order_by(DBIntakeRequest.created_at.desc()).limit(limit).all()
            )
            return [self._to_training_request(row) for row in rows]

    def confirm_intake_request(
        self,
        request_id: str,
        *,
        confirmed_by: str,
        confirmed_at: datetime,
        confirmation_note: str | None = None,
    ) -> None:
        """Flip a request to CONFIRMED and stamp the human approver (no-op if absent)."""
        with self._session() as session:
            row = session.get(DBIntakeRequest, request_id)
            if row is None:
                return
            row.status = IntakeStatus.CONFIRMED.value
            row.confirmed_by = confirmed_by
            row.confirmed_at = confirmed_at
            if confirmation_note is not None:
                row.confirmation_note = confirmation_note
            session.commit()
