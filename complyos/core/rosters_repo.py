"""Roster-snapshot persistence for LocalRepository.

Backs :class:`complyos.services.rosters.RostersService`. Mirrors the existing
aggregate-mixin shape (intake, source-intel, notifications): a save/get/list
trio plus an approval-transition writer, all tenant-scoped. The persisted entity
is the typed :class:`RosterSnapshot`; the learners x learning-items roster view
(:class:`RosterPacket`/:class:`RosterRow`) is derived deterministically by the
service from the already-normalized learning records and is not stored.
"""

from __future__ import annotations

from datetime import datetime

from complyos.core.repository_base import RepositoryBase
from complyos.core.repository_mappers import RepositoryMappers
from complyos.models.database import DBRosterSnapshot
from complyos.models.domain import RosterSnapshot, RosterStatus


class RosterSnapshotRepositoryMixin(RepositoryBase, RepositoryMappers):
    """Persist and query tenant-scoped roster snapshots."""

    def save_roster_snapshot(self, snapshot: RosterSnapshot) -> None:
        """Insert or replace a captured roster snapshot (tenant carried on row)."""
        with self._session() as session:
            session.merge(
                DBRosterSnapshot(
                    id=snapshot.id,
                    tenant_id=snapshot.tenant_id,
                    label=snapshot.label,
                    source_system=snapshot.source_system,
                    batch_id=snapshot.batch_id,
                    status=snapshot.status.value,
                    created_by=snapshot.created_by,
                    created_at=snapshot.created_at,
                    approved_by=snapshot.approved_by,
                    approved_at=snapshot.approved_at,
                    approval_note=snapshot.approval_note,
                )
            )
            session.commit()

    def get_roster_snapshot(self, snapshot_id: str) -> RosterSnapshot | None:
        """Fetch one snapshot by id (caller checks tenant ownership)."""
        with self._session() as session:
            row = session.get(DBRosterSnapshot, snapshot_id)
            if row is None:
                return None
            return self._to_roster_snapshot(row)

    def list_roster_snapshots(
        self,
        *,
        tenant_id: str,
        status: RosterStatus | None = None,
        limit: int = 100,
    ) -> list[RosterSnapshot]:
        """List a tenant's roster snapshots, newest first, optionally by status."""
        with self._session() as session:
            query = session.query(DBRosterSnapshot).where(
                DBRosterSnapshot.tenant_id == tenant_id
            )
            if status is not None:
                query = query.where(DBRosterSnapshot.status == status.value)
            rows = (
                query.order_by(DBRosterSnapshot.created_at.desc()).limit(limit).all()
            )
            return [self._to_roster_snapshot(row) for row in rows]

    def approve_roster_snapshot(
        self,
        snapshot_id: str,
        *,
        approved_by: str,
        approved_at: datetime,
        approval_note: str | None = None,
    ) -> None:
        """Flip a snapshot to APPROVED and stamp the human approver (no-op if absent)."""
        with self._session() as session:
            row = session.get(DBRosterSnapshot, snapshot_id)
            if row is None:
                return
            row.status = RosterStatus.APPROVED.value
            row.approved_by = approved_by
            row.approved_at = approved_at
            if approval_note is not None:
                row.approval_note = approval_note
            session.commit()
