"""Rosters: preview/quarantine -> proposal-only roster view -> human-approved import.

Rosters is the LearningOps Suite's normalized-attendance/enrollment/completion
view across LMS, HRIS, and CSV exports. It is a roster-centric *view* over the
EXISTING import + normalization + audit machinery, not a second importer: it
reuses :class:`complyos.services.imports.ImportService` (preview -> quarantine ->
promote) and the shared :mod:`complyos.connectors.normalization` status mapping,
so normalization and the quarantine guardrail are not re-implemented here.

This service follows the repeatable "suite-module" shape
(see ``docs/suite-module-pattern.md``) — the same five beats as Intake:

1. **Capture** — :meth:`request_snapshot` routes a source export through
   ``ImportService.preview`` (which quarantines questionable data) and persists a
   :class:`RosterSnapshot` in ``DRAFT`` pointing at the quarantined batch.
   Previewing data is NOT the same as letting it mutate the normalized truth.
2. **Draft packet (proposal-only)** — :meth:`draft_packet` presents the current
   learners x learning-items rows (with their already-normalized status) and the
   quarantine state of the pending batch. It carries ``confirms_import=False`` /
   ``requires_human_approval=True`` and writes NO state change.
3. **Human-approval gate** — :meth:`approve_snapshot` is the single elevated step
   that promotes the quarantined batch through ``ImportService.promote`` (the
   only mutate path — never a bypass) and flips the snapshot to ``APPROVED``,
   stamping who approved and when.
4. **Action log** — every capture, draft, and approval writes an action-log entry.
5. **Surfaces + tests** — the same service is reachable from CLI, API v1, and MCP
   with cross-surface parity.

Authz split (mirrors intake/attestations): requesting a snapshot + reading the
roster is gated at ``rosters:read`` (which the proposal-only
``agent_service_account`` role holds); approving the snapshot's import is gated
at ``rosters:approve`` (which that role deliberately lacks). AI/agents can
preview and present; only an elevated human lets an import mutate truth.

PII discipline: roster rows address learners by opaque ``user_id``, never by
name/email.

Claim boundary: a roster view — even an approved one — records that data was
previewed, normalized, and (optionally) human-approved for import. It never
asserts anyone is "certified" or "compliant".
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    LearningRecordStatus,
    RosterPacket,
    RosterRow,
    RosterSnapshot,
    RosterStatus,
)
from complyos.services.context import (
    PERM_ROSTERS_APPROVE,
    PERM_ROSTERS_READ,
    ActorContext,
    require_permission,
)
from complyos.services.imports import ImportPreviewRequest, ImportService

# Normalized statuses the suite spec presents on a roster (assigned/complete/
# overdue/expired/exempt + the in-flight in_progress/not_started). This is the
# presentation vocabulary; the values are computed by the shared normalization
# layer, not re-derived here.
_ROSTER_STATUSES: tuple[LearningRecordStatus, ...] = tuple(LearningRecordStatus)


class RostersService:
    """Authorization-gated roster snapshot capture, roster-view drafting, and import approval."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()
        # Reuse the existing import lifecycle: quarantine/preview/promote is its
        # job, so Rosters never re-implements normalization or a mutate bypass.
        self.imports = ImportService(self.repository)

    # ------------------------------------------------------------------
    # 1. Capture (routes through ImportService preview/quarantine)
    # ------------------------------------------------------------------
    def request_snapshot(
        self,
        context: ActorContext,
        *,
        label: str,
        csv_text: str | None = None,
        path: str | None = None,
        source_system: str = "csv",
    ) -> RosterSnapshot:
        """Capture a roster snapshot by previewing a source export into quarantine.

        Gated at ``rosters:read`` (the proposal-only/agent role holds this). The
        export is routed through ``ImportService.preview``, which validates and
        QUARANTINES the batch — nothing is written to the normalized truth. The
        snapshot is persisted in ``DRAFT`` and records which batch was previewed.
        Promotion is a separate, human-gated step (:meth:`approve_snapshot`).
        """
        require_permission(context, PERM_ROSTERS_READ)

        label = label.strip()
        if not label:
            raise ValueError("label is required to capture a roster snapshot")

        preview = self.imports.preview(
            context,
            ImportPreviewRequest(
                source_system=source_system,
                profile=context.track,
                csv_text=csv_text,
                path=path,
            ),
        )
        snapshot = RosterSnapshot(
            id=str(uuid4()),
            tenant_id=context.tenant_id,
            label=label,
            source_system=source_system,
            batch_id=preview.batch_id,
            status=RosterStatus.DRAFT,
            created_by=context.actor_id,
            created_at=datetime.now(UTC),
        )
        self.repository.save_roster_snapshot(snapshot)
        self._log(
            context,
            action="rosters.snapshot.request",
            object_id=snapshot.id,
            metadata={
                "label": label,
                "batch_id": preview.batch_id,
                "batch_status": preview.status,
                "can_promote": preview.can_promote,
            },
        )
        return snapshot

    # ------------------------------------------------------------------
    # 2. Draft packet (proposal-only roster view)
    # ------------------------------------------------------------------
    def draft_packet(
        self,
        context: ActorContext,
        *,
        snapshot_id: str,
    ) -> RosterPacket:
        """Draft a proposal-only roster view for a captured snapshot.

        Gated at ``rosters:read``. Presents the current learners x learning-items
        rows with their already-normalized status and reports the quarantine
        state (``can_promote`` / blocked-row count) of the pending import batch.
        It carries ``confirms_import=False`` and ``requires_human_approval=True``
        and writes NO state change: drafting can never promote the batch.
        """
        require_permission(context, PERM_ROSTERS_READ)
        snapshot = self._require_snapshot(context, snapshot_id)

        batch = self.repository.get_import_batch(snapshot.batch_id)
        rows = (
            self.repository.list_import_rows(snapshot.batch_id) if batch is not None else []
        )
        can_promote = self.imports._can_promote_rows(rows) if rows else False
        blocked = sum(
            1
            for row in rows
            if row["validation_status"] in {"PENDING", "REJECTED", "NEEDS_DECISION"}
        )

        roster_rows = self._roster_rows(snapshot)
        status_counts = self._status_counts(roster_rows)
        return RosterPacket(
            snapshot_id=snapshot.id,
            tenant_id=snapshot.tenant_id,
            label=snapshot.label,
            source_system=snapshot.source_system,
            batch_id=snapshot.batch_id,
            batch_status=batch["status"] if batch is not None else "unknown",
            can_promote=can_promote,
            blocked_row_count=blocked,
            rows=roster_rows,
            status_counts=status_counts,
            confirms_import=False,
            requires_human_approval=True,
            drafted_by_provider="deterministic",
        )

    # ------------------------------------------------------------------
    # 3. Human-approval gate (the quarantine guardrail)
    # ------------------------------------------------------------------
    def approve_snapshot(
        self,
        context: ActorContext,
        *,
        snapshot_id: str,
        note: str | None = None,
    ) -> RosterSnapshot:
        """Approve a snapshot: promote its quarantined batch and mark it APPROVED.

        Gated at ``rosters:approve`` — an ELEVATED permission the proposal-only
        ``agent_service_account`` role deliberately lacks. This is the only path
        that lets the previewed data mutate the normalized truth: it routes
        through ``ImportService.promote`` (never a bypass), then stamps
        ``approved_by``/``approved_at``. A snapshot already withdrawn or approved
        cannot be re-approved; a batch that still has quarantined rows refuses to
        promote (ImportService keeps it quarantined) and the snapshot stays DRAFT.
        """
        require_permission(context, PERM_ROSTERS_APPROVE)
        snapshot = self._require_snapshot(context, snapshot_id)

        if snapshot.status is RosterStatus.APPROVED:
            raise ValueError(f"roster snapshot already approved: {snapshot_id}")
        if snapshot.status is RosterStatus.WITHDRAWN:
            raise ValueError(f"withdrawn roster snapshot cannot be approved: {snapshot_id}")

        promotion = self.imports.promote(context, snapshot.batch_id)
        if promotion.status != "PROMOTED":
            # The batch still has quarantined rows; ImportService refused to
            # promote. Honor the guardrail: do not approve a snapshot whose data
            # never cleared quarantine.
            self._log(
                context,
                action="rosters.snapshot.approve",
                object_id=snapshot_id,
                result="blocked",
                metadata={
                    "batch_id": snapshot.batch_id,
                    "batch_status": promotion.status,
                    "blocked_rows": promotion.blocked_rows,
                },
            )
            raise ValueError(
                f"roster snapshot batch is still quarantined ({promotion.status}); "
                "clear blocking rows before approval"
            )

        approved_at = datetime.now(UTC)
        clean_note = _clean(note)
        self.repository.approve_roster_snapshot(
            snapshot_id,
            approved_by=context.actor_id,
            approved_at=approved_at,
            approval_note=clean_note,
        )
        self._log(
            context,
            action="rosters.snapshot.approve",
            object_id=snapshot_id,
            metadata={
                "approved_by": context.actor_id,
                "batch_id": snapshot.batch_id,
                "promoted_rows": promotion.promoted_rows,
                "note": clean_note,
            },
        )
        approved = self.repository.get_roster_snapshot(snapshot_id)
        assert approved is not None  # just written
        return approved

    # ------------------------------------------------------------------
    # 4. Read
    # ------------------------------------------------------------------
    def list_snapshots(
        self,
        context: ActorContext,
        *,
        status: RosterStatus | str | None = None,
    ) -> list[RosterSnapshot]:
        """List the tenant's roster snapshots (``rosters:read``), optionally by status.

        Tenant-scoped at the repository: only snapshots owned by the caller's
        tenant are returned, so one tenant can never read another's roster queue.
        """
        require_permission(context, PERM_ROSTERS_READ)
        resolved_status = self._coerce_status(status) if status is not None else None
        return self.repository.list_roster_snapshots(
            tenant_id=context.tenant_id, status=resolved_status
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _require_snapshot(
        self, context: ActorContext, snapshot_id: str
    ) -> RosterSnapshot:
        """Load a snapshot and refuse cross-tenant access (ownership, not permission)."""
        snapshot = self.repository.get_roster_snapshot(snapshot_id)
        if snapshot is None:
            raise ValueError(f"unknown roster snapshot: {snapshot_id}")
        if snapshot.tenant_id != context.tenant_id:
            raise PermissionError("cannot act on a roster snapshot owned by another tenant")
        return snapshot

    def _roster_rows(self, snapshot: RosterSnapshot) -> list[RosterRow]:
        """Present the already-normalized learning records as roster rows.

        Reads the normalized truth (not the quarantined batch): the roster view
        shows the current learners x learning-items state. Status is the value
        the shared normalization layer already computed — never re-derived here.
        """
        records = self.repository.list_learning_records(source_system=snapshot.source_system)
        return [
            RosterRow(
                user_id=record.user_id,
                course_id=record.course_id,
                status=record.status,
                source_system=record.source_system,
                due_date=record.due_date,
                completed_date=record.completed_date,
                expires_at=record.expires_at,
            )
            for record in records
        ]

    @staticmethod
    def _status_counts(rows: list[RosterRow]) -> dict[str, int]:
        counts = {status.value: 0 for status in _ROSTER_STATUSES}
        for row in rows:
            counts[row.status.value] = counts.get(row.status.value, 0) + 1
        return counts

    @staticmethod
    def _coerce_status(status: RosterStatus | str) -> RosterStatus:
        if isinstance(status, RosterStatus):
            return status
        try:
            return RosterStatus(status)
        except ValueError as exc:
            valid = ", ".join(sorted(RosterStatus.values()))
            raise ValueError(
                f"unknown roster status {status!r}; expected one of: {valid}"
            ) from exc

    def _log(
        self,
        context: ActorContext,
        *,
        action: str,
        object_id: str,
        metadata: dict[str, object],
        result: str = "success",
    ) -> None:
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action=action,
            object_type="roster_snapshot",
            object_id=object_id,
            result=result,
            request_id=context.request_id,
            metadata=metadata,
        )


def _clean(value: str | None) -> str | None:
    """Trim a free-text field; treat blank/whitespace-only as absent (None)."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
