"""Import lifecycle + AI-proposal persistence for LocalRepository."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from complyos.core.repository_base import RepositoryBase
from complyos.core.repository_mappers import RepositoryMappers
from complyos.core.time import utc_now
from complyos.models.database import (
    DBAIProposal,
    DBAIProvenance,
    DBImportBatch,
    DBImportDecision,
    DBImportRow,
)


class ImportRepositoryMixin(RepositoryBase, RepositoryMappers):
    """Import batches/rows/decisions and AI proposals (the ingestion boundary)."""

    # ------------------------------------------------------------------
    # Import lifecycle
    # ------------------------------------------------------------------
    def save_import_batch(self, batch: dict[str, Any]) -> None:
        with self._session() as session:
            db_batch = DBImportBatch(
                id=batch["id"],
                tenant_id=batch["tenant_id"],
                source_system=batch["source_system"],
                profile=batch["profile"],
                raw_file_hash=batch["raw_file_hash"],
                status=batch["status"],
                idempotency_key=batch["idempotency_key"],
                created_by=batch["created_by"],
                created_at=batch.get("created_at") or utc_now(),
                batch_metadata=batch.get("metadata") or {},
            )
            session.add(db_batch)
            session.commit()

    def get_import_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            batch = session.get(DBImportBatch, batch_id)
            return self._to_import_batch_dict(batch) if batch else None

    def get_import_batch_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        with self._session() as session:
            batch = (
                session.query(DBImportBatch)
                .where(
                    DBImportBatch.tenant_id == tenant_id,
                    DBImportBatch.idempotency_key == idempotency_key,
                )
                .first()
            )
            return self._to_import_batch_dict(batch) if batch else None

    def update_import_batch_status(
        self,
        batch_id: str,
        status: str,
        *,
        promoted_by: str | None = None,
        promoted_at: datetime | None = None,
    ) -> None:
        with self._session() as session:
            batch = session.get(DBImportBatch, batch_id)
            if batch is None:
                return
            batch.status = status
            if promoted_by is not None:
                batch.promoted_by = promoted_by
            if promoted_at is not None:
                batch.promoted_at = promoted_at
            session.commit()

    def save_import_rows(self, batch_id: str, rows: list[dict[str, Any]]) -> None:
        with self._session() as session:
            for row in rows:
                session.add(
                    DBImportRow(
                        id=row["id"],
                        batch_id=batch_id,
                        row_number=row["row_number"],
                        normalized_payload=row["normalized_payload"],
                        raw_payload_hash=row["raw_payload_hash"],
                        validation_status=row["validation_status"],
                        rejection_codes=row.get("rejection_codes") or [],
                        source_record_id=row.get("source_record_id"),
                        issues=row.get("issues") or [],
                    )
                )
            session.commit()

    def list_import_rows(self, batch_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(DBImportRow)
                .where(DBImportRow.batch_id == batch_id)
                .order_by(DBImportRow.row_number)
                .all()
            )
            return [self._to_import_row_dict(row) for row in rows]

    def update_import_row_status(self, batch_id: str, row_id: str, status: str) -> None:
        with self._session() as session:
            row = (
                session.query(DBImportRow)
                .where(DBImportRow.batch_id == batch_id, DBImportRow.id == row_id)
                .first()
            )
            if row is None:
                return
            row.validation_status = status
            session.commit()

    def save_import_decision(self, decision: dict[str, Any]) -> None:
        with self._session() as session:
            session.add(
                DBImportDecision(
                    id=decision["id"],
                    batch_id=decision["batch_id"],
                    row_id=decision["row_id"],
                    decision_type=decision["decision_type"],
                    decision_payload=decision.get("decision_payload") or {},
                    decided_by=decision["decided_by"],
                    decided_at=decision.get("decided_at") or utc_now(),
                    reason=decision.get("reason"),
                )
            )
            session.commit()

    def list_import_decisions(self, batch_id: str) -> list[dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(DBImportDecision)
                .where(DBImportDecision.batch_id == batch_id)
                .order_by(DBImportDecision.decided_at.desc())
                .all()
            )
            return [self._to_import_decision_dict(row) for row in rows]

    # ------------------------------------------------------------------
    # AI proposals
    # ------------------------------------------------------------------
    def save_ai_proposal(self, proposal: dict[str, Any]) -> None:
        provenance = proposal.get("provenance") or {}
        with self._session() as session:
            session.add(
                DBAIProposal(
                    id=proposal["id"],
                    tenant_id=proposal["tenant_id"],
                    proposal_type=proposal["proposal_type"],
                    input_hash=proposal["input_hash"],
                    output_hash=proposal["output_hash"],
                    status=proposal["status"],
                    created_by=proposal["created_by"],
                    created_at=proposal.get("created_at") or utc_now(),
                    output=proposal.get("output") or {},
                )
            )
            session.add(
                DBAIProvenance(
                    proposal_id=proposal["id"],
                    model_provider=provenance.get("model_provider", "unknown"),
                    model_name=provenance.get("model_name", "unknown"),
                    prompt_hash=provenance.get("prompt_hash", ""),
                    redaction_policy=provenance.get("redaction_policy", "unknown"),
                    response_hash=provenance.get("response_hash", proposal["output_hash"]),
                    usage_metadata=provenance,
                )
            )
            session.commit()

    def get_ai_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self._session() as session:
            proposal = session.get(DBAIProposal, proposal_id)
            if proposal is None:
                return None
            provenance = session.get(DBAIProvenance, proposal_id)
            return self._to_ai_proposal_dict(proposal, provenance)

    def update_ai_proposal_status(
        self,
        proposal_id: str,
        status: str,
        *,
        approved_by: str | None = None,
        approved_at: datetime | None = None,
    ) -> None:
        with self._session() as session:
            proposal = session.get(DBAIProposal, proposal_id)
            if proposal is None:
                return
            proposal.status = status
            if approved_by is not None:
                proposal.approved_by = approved_by
            if approved_at is not None:
                proposal.approved_at = approved_at
            session.commit()

