"""Gated CSV/import lifecycle for ComplyOS.

The CSV connector remains read-only. This service handles operator uploads:
preview -> quarantine/decisions -> promote. Bad inputs fail closed and never
mutate active learning records.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from complyos.connectors.normalization import ENROLLMENT_ALIASES, STATUS_SYNONYMS
from complyos.connectors.normalization import normalize_header as _normalize_header
from complyos.connectors.normalization import parse_date as _parse_date
from complyos.connectors.normalization import parse_datetime as _parse_datetime
from complyos.connectors.normalization import parse_float as _parse_float
from complyos.connectors.normalization import remap_row as _remap_row
from complyos.connectors.normalization import to_learning_status as _to_learning_status
from complyos.core.repository import LocalRepository
from complyos.models.domain import LearningRecord, LearningRecordStatus
from complyos.services.context import (
    PERM_IMPORT_DECIDE,
    PERM_IMPORT_PREVIEW,
    PERM_IMPORT_PROMOTE,
    ActorContext,
    require_permission,
)

FORMULA_PREFIXES = ("=", "+", "-", "@")
TENANT_ALIASES = {"tenant_id": ["tenantid", "tenant", "orgid", "organizationid"]}
TRACK_ALIASES = {"track": ["track", "profile", "context"]}
IMPORT_BATCH_STATES = {
    "DRAFT",
    "PREVIEWED",
    "QUARANTINED",
    "PROMOTION_PENDING",
    "PROMOTED",
    "REJECTED",
    "EXPIRED",
    "PROMOTION_FAILED",
}
ROW_STATES = {"PENDING", "VALID", "REJECTED", "NEEDS_DECISION", "PROMOTED", "IGNORED"}
BLOCKING_ROW_STATES = {"REJECTED", "NEEDS_DECISION", "PENDING"}


class ImportIssue(BaseModel):
    code: str
    severity: str = "warning"
    row_number: int | None = None
    column: str | None = None
    message: str


class ImportPreviewRequest(BaseModel):
    source_system: str = "csv"
    profile: str = "workforce"
    csv_text: str | None = None
    path: str | None = None
    import_type: str = "learning_records"
    source_exported_at: datetime | None = None
    max_export_age_days: int | None = 14


class ImportPreviewResult(BaseModel):
    batch_id: str
    tenant_id: str
    source_system: str
    profile: str
    status: str
    idempotency_key: str
    raw_file_hash: str
    total_rows: int
    row_counts: dict[str, int]
    unexpected_columns: list[str] = Field(default_factory=list)
    issues: list[ImportIssue] = Field(default_factory=list)
    can_promote: bool
    rows_preview: list[dict[str, Any]] = Field(default_factory=list)
    actor_context: dict[str, str] = Field(default_factory=dict)


class ImportDecisionResult(BaseModel):
    batch_id: str
    row_id: str
    decision_type: str
    row_status: str
    recorded: bool


class ImportPromotionResult(BaseModel):
    batch_id: str
    status: str
    promoted_rows: int
    blocked_rows: int
    evidence_id: str | None = None
    issues: list[ImportIssue] = Field(default_factory=list)


class ImportService:
    """Service-backed import preview/decision/promotion lifecycle."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def preview(self, context: ActorContext, request: ImportPreviewRequest) -> ImportPreviewResult:
        require_permission(context, PERM_IMPORT_PREVIEW)
        csv_text = self._load_csv_text(request)
        raw_file_hash = self._sha256(csv_text)
        idempotency_key = self._idempotency_key(
            context.tenant_id, request.source_system, request.profile, raw_file_hash
        )

        existing = self.repository.get_import_batch_by_idempotency_key(
            context.tenant_id, idempotency_key
        )
        if existing is not None:
            rows = self.repository.list_import_rows(existing["id"])
            issues = [ImportIssue(**issue) for row in rows for issue in row.get("issues", [])]
            row_counts = self._row_counts(rows)
            return ImportPreviewResult(
                batch_id=existing["id"],
                tenant_id=existing["tenant_id"],
                source_system=existing["source_system"],
                profile=existing["profile"],
                status=existing["status"],
                idempotency_key=existing["idempotency_key"],
                raw_file_hash=existing["raw_file_hash"],
                total_rows=len(rows),
                row_counts=row_counts,
                unexpected_columns=sorted(
                    {
                        issue.column
                        for issue in issues
                        if issue.code == "UNEXPECTED_COLUMN" and issue.column
                    }
                ),
                issues=issues,
                can_promote=self._can_promote_rows(rows),
                rows_preview=[row["normalized_payload"] for row in rows[:10]],
                actor_context=context.public_dict(),
            )

        rows, issues, unexpected_columns = self._validate_rows(csv_text, context, request)
        batch_id = str(uuid4())
        status = "QUARANTINED"
        batch = {
            "id": batch_id,
            "tenant_id": context.tenant_id,
            "source_system": request.source_system,
            "profile": request.profile,
            "raw_file_hash": raw_file_hash,
            "status": status,
            "idempotency_key": idempotency_key,
            "created_by": context.actor_id,
            "created_at": datetime.now(UTC),
            "metadata": {
                "import_type": request.import_type,
                "source_exported_at": request.source_exported_at.isoformat()
                if request.source_exported_at
                else None,
            },
        }
        self.repository.save_import_batch(batch)
        self.repository.save_import_rows(batch_id, rows)
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="import.preview",
            object_type="import_batch",
            object_id=batch_id,
            result="success",
            request_id=context.request_id,
            metadata={"row_count": len(rows), "can_promote": self._can_promote_rows(rows)},
        )
        return ImportPreviewResult(
            batch_id=batch_id,
            tenant_id=context.tenant_id,
            source_system=request.source_system,
            profile=request.profile,
            status=status,
            idempotency_key=idempotency_key,
            raw_file_hash=raw_file_hash,
            total_rows=len(rows),
            row_counts=self._row_counts(rows),
            unexpected_columns=unexpected_columns,
            issues=issues,
            can_promote=self._can_promote_rows(rows),
            rows_preview=[row["normalized_payload"] for row in rows[:10]],
            actor_context=context.public_dict(),
        )

    def preview_csv_path(
        self,
        context: ActorContext,
        path: str | Path,
        *,
        source_system: str = "csv",
        profile: str = "workforce",
    ) -> ImportPreviewResult:
        request = ImportPreviewRequest(
            source_system=source_system,
            profile=profile,
            path=str(path),
        )
        return self.preview(context, request)

    def decide(
        self,
        context: ActorContext,
        *,
        batch_id: str,
        row_id: str,
        decision_type: str,
        reason: str | None = None,
        decision_payload: dict[str, Any] | None = None,
    ) -> ImportDecisionResult:
        require_permission(context, PERM_IMPORT_DECIDE)
        rows = self.repository.list_import_rows(batch_id)
        row = next((item for item in rows if item["id"] == row_id), None)
        if row is None:
            raise ValueError(f"unknown import row: {row_id}")
        allowed_decisions = {
            "accept",
            "reject",
            "map_field",
            "merge_duplicate",
            "ignore_row",
            "require_manual_review",
        }
        if decision_type not in allowed_decisions:
            raise ValueError(f"unsupported decision_type: {decision_type}")

        new_status = row["validation_status"]
        if decision_type in {"accept", "merge_duplicate", "map_field"}:
            new_status = "VALID"
        elif decision_type == "reject":
            new_status = "REJECTED"
        elif decision_type == "ignore_row":
            new_status = "IGNORED"
        elif decision_type == "require_manual_review":
            new_status = "NEEDS_DECISION"

        self.repository.save_import_decision(
            {
                "id": str(uuid4()),
                "batch_id": batch_id,
                "row_id": row_id,
                "decision_type": decision_type,
                "decision_payload": decision_payload or {},
                "decided_by": context.actor_id,
                "decided_at": datetime.now(UTC),
                "reason": reason,
            }
        )
        self.repository.update_import_row_status(batch_id, row_id, new_status)
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="import.decide",
            object_type="import_row",
            object_id=row_id,
            result="success",
            request_id=context.request_id,
            metadata={"decision_type": decision_type, "batch_id": batch_id},
        )
        return ImportDecisionResult(
            batch_id=batch_id,
            row_id=row_id,
            decision_type=decision_type,
            row_status=new_status,
            recorded=True,
        )

    def promote(self, context: ActorContext, batch_id: str) -> ImportPromotionResult:
        require_permission(context, PERM_IMPORT_PROMOTE)
        batch = self.repository.get_import_batch(batch_id)
        if batch is None:
            raise ValueError(f"unknown import batch: {batch_id}")
        if batch["tenant_id"] != context.tenant_id:
            raise PermissionError("cannot promote import batch for another tenant")
        if batch["status"] == "PROMOTED":
            rows = self.repository.list_import_rows(batch_id)
            return ImportPromotionResult(
                batch_id=batch_id,
                status="PROMOTED",
                promoted_rows=len([r for r in rows if r["validation_status"] == "PROMOTED"]),
                blocked_rows=0,
            )

        rows = self.repository.list_import_rows(batch_id)
        blocking_rows = [row for row in rows if row["validation_status"] in BLOCKING_ROW_STATES]
        if blocking_rows:
            self.repository.update_import_batch_status(batch_id, "QUARANTINED")
            self.repository.save_action_log(
                tenant_id=context.tenant_id,
                actor_id=context.actor_id,
                surface=context.surface,
                action="import.promote",
                object_type="import_batch",
                object_id=batch_id,
                result="blocked",
                request_id=context.request_id,
                metadata={"blocked_rows": len(blocking_rows)},
            )
            return ImportPromotionResult(
                batch_id=batch_id,
                status="QUARANTINED",
                promoted_rows=0,
                blocked_rows=len(blocking_rows),
                issues=[
                    ImportIssue(
                        code="PROMOTION_BLOCKED",
                        severity="blocker",
                        message="batch has rejected/pending/needs-decision rows",
                    )
                ],
            )

        promoted = 0
        self.repository.update_import_batch_status(batch_id, "PROMOTION_PENDING")
        try:
            row_record_pairs: list[tuple[str, LearningRecord]] = []
            for row in rows:
                if row["validation_status"] == "IGNORED":
                    continue
                record = self._learning_record_from_row(row, batch)
                row_record_pairs.append((row["id"], record))
                promoted += 1
            output_hash = self._sha256(json.dumps({"batch_id": batch_id, "promoted": promoted}))
            evidence_id = self.repository.promote_import_learning_records(
                batch_id=batch_id,
                row_record_pairs=row_record_pairs,
                promoted_by=context.actor_id,
                promoted_at=datetime.now(UTC),
                evidence_entry={
                    "timestamp": datetime.now(UTC),
                    "query_type": "import.promote",
                    "query_params": {"batch_id": batch_id, "tenant_id": context.tenant_id},
                    "raw_data_hash": batch["raw_file_hash"],
                    "transformation_steps": [
                        "validated_csv_preview",
                        "blocked_rows_checked",
                        "learning_records_upserted",
                    ],
                    "output_hash": output_hash,
                    "output_summary": f"Promoted {promoted} rows from import batch {batch_id}",
                },
            )
            self.repository.save_action_log(
                tenant_id=context.tenant_id,
                actor_id=context.actor_id,
                surface=context.surface,
                action="import.promote",
                object_type="import_batch",
                object_id=batch_id,
                result="success",
                request_id=context.request_id,
                metadata={"promoted_rows": promoted, "evidence_id": evidence_id},
            )
            return ImportPromotionResult(
                batch_id=batch_id,
                status="PROMOTED",
                promoted_rows=promoted,
                blocked_rows=0,
                evidence_id=evidence_id,
            )
        except Exception:
            self.repository.update_import_batch_status(batch_id, "PROMOTION_FAILED")
            raise

    @staticmethod
    def _load_csv_text(request: ImportPreviewRequest) -> str:
        if request.csv_text is not None:
            return request.csv_text
        if request.path is None:
            raise ValueError("either csv_text or path is required")
        return Path(request.path).read_text(encoding="utf-8-sig")

    def _validate_rows(
        self,
        csv_text: str,
        context: ActorContext,
        request: ImportPreviewRequest,
    ) -> tuple[list[dict[str, Any]], list[ImportIssue], list[str]]:
        reader = csv.DictReader(io.StringIO(csv_text))
        headers = reader.fieldnames or []
        allowed_headers = self._allowed_headers()
        normalized_headers = {_normalize_header(header): header for header in headers if header}
        unexpected_columns = sorted(
            original
            for normalized, original in normalized_headers.items()
            if normalized not in allowed_headers
        )
        global_issues: list[ImportIssue] = [
            ImportIssue(
                code="UNEXPECTED_COLUMN",
                severity="warning",
                column=column,
                message="unexpected column must be mapped, ignored, or removed before promotion",
            )
            for column in unexpected_columns
        ]

        if (
            request.source_exported_at
            and request.max_export_age_days is not None
            and request.source_exported_at
            < datetime.now(UTC) - timedelta(days=request.max_export_age_days)
        ):
            global_issues.append(
                ImportIssue(
                    code="STALE_EXPORT",
                    severity="warning",
                    message="source export is older than the configured freshness policy",
                )
            )

        rows: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str | None]] = set()
        raw_rows = list(reader)
        if not raw_rows:
            global_issues.append(
                ImportIssue(
                    code="PARTIAL_LOAD",
                    severity="blocker",
                    message="CSV import has no data rows",
                )
            )

        # File-scoped warnings still gate every row to NEEDS_DECISION, but are
        # reported once at the batch level rather than copied into each row
        # (which made the stored evidence and preview O(rows x file_issues) noisy
        # and mislabeled each row as owning a file-level problem).
        file_decision_warning = any(
            issue.code in {"UNEXPECTED_COLUMN", "STALE_EXPORT"} for issue in global_issues
        )

        for index, raw_row in enumerate(raw_rows, start=2):
            row_issues: list[ImportIssue] = []
            mapped = _remap_row(raw_row, ENROLLMENT_ALIASES)
            tenant_map = _remap_row(raw_row, TENANT_ALIASES)
            track_map = _remap_row(raw_row, TRACK_ALIASES)

            for column, value in raw_row.items():
                if value and value.strip().startswith(FORMULA_PREFIXES):
                    row_issues.append(
                        ImportIssue(
                            code="FORMULA_INJECTION",
                            severity="blocker",
                            row_number=index,
                            column=column,
                            message="spreadsheet formula-like value rejected",
                        )
                    )
            if "user_id" not in mapped or "course_id" not in mapped:
                row_issues.append(
                    ImportIssue(
                        code="MISSING_REQUIRED_FIELD",
                        severity="blocker",
                        row_number=index,
                        message="user_id and course_id are required for learning-record imports",
                    )
                )
            if tenant_map.get("tenant_id") and tenant_map["tenant_id"] != context.tenant_id:
                row_issues.append(
                    ImportIssue(
                        code="MIXED_TENANT",
                        severity="blocker",
                        row_number=index,
                        column="tenant_id",
                        message="row belongs to a different tenant",
                    )
                )
            if track_map.get("track") and track_map["track"] != context.track:
                row_issues.append(
                    ImportIssue(
                        code="MIXED_TRACK",
                        severity="blocker",
                        row_number=index,
                        column="track",
                        message="row belongs to a different workforce/campus track",
                    )
                )

            source_record_id = mapped.get("source_record_id") or mapped.get("id")
            duplicate_key = (
                mapped.get("user_id", ""),
                mapped.get("course_id", ""),
                source_record_id,
            )
            if all(duplicate_key[:2]) and duplicate_key in seen_keys:
                row_issues.append(
                    ImportIssue(
                        code="DUPLICATE_ROW",
                        severity="warning",
                        row_number=index,
                        message=(
                            "duplicate learner/course/source record requires an explicit decision"
                        ),
                    )
                )
            else:
                seen_keys.add(duplicate_key)

            has_blocker = any(issue.severity == "blocker" for issue in row_issues)
            has_decision_warning = file_decision_warning or any(
                issue.code == "DUPLICATE_ROW" for issue in row_issues
            )
            if has_blocker:
                status = "REJECTED"
            elif has_decision_warning:
                status = "NEEDS_DECISION"
            else:
                status = "VALID"
            rows.append(
                {
                    "id": str(uuid4()),
                    "row_number": index,
                    "normalized_payload": mapped,
                    "raw_payload_hash": self._sha256(json.dumps(raw_row, sort_keys=True)),
                    "validation_status": status,
                    "rejection_codes": [issue.code for issue in row_issues],
                    "source_record_id": source_record_id,
                    "issues": [issue.model_dump(mode="json") for issue in row_issues],
                }
            )

        # File-global issues are reported once here; per-row issues follow. This
        # also surfaces file-level issues (e.g. PARTIAL_LOAD) when there are no
        # data rows, which the previous per-row flatten silently dropped.
        issues = list(global_issues) + [
            issue
            for row in rows
            for issue in (ImportIssue(**item) for item in row["issues"])
        ]
        return rows, issues, unexpected_columns

    @staticmethod
    def _allowed_headers() -> set[str]:
        allowed: set[str] = set()
        for aliases in [ENROLLMENT_ALIASES, TENANT_ALIASES, TRACK_ALIASES]:
            for canonical, candidates in aliases.items():
                allowed.add(_normalize_header(canonical))
                allowed.update(candidates)
        return allowed

    @staticmethod
    def _row_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
        counts = dict.fromkeys(sorted(ROW_STATES), 0)
        for row in rows:
            counts[row["validation_status"]] = counts.get(row["validation_status"], 0) + 1
        return counts

    @staticmethod
    def _can_promote_rows(rows: list[dict[str, Any]]) -> bool:
        return bool(rows) and all(row["validation_status"] in {"VALID", "IGNORED"} for row in rows)

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def _idempotency_key(
        cls,
        tenant_id: str,
        source_system: str,
        profile: str,
        raw_file_hash: str,
    ) -> str:
        return cls._sha256("|".join([tenant_id, source_system, profile, raw_file_hash]))

    @staticmethod
    def _learning_record_from_row(row: dict[str, Any], batch: dict[str, Any]) -> LearningRecord:
        payload = row["normalized_payload"]
        raw_status = payload.get("status", "not_started").lower().replace(" ", "_")
        enrollment_status = STATUS_SYNONYMS.get(raw_status)
        expires_at = _parse_date(payload.get("expires_at"))
        record_id = payload.get("id") or f"import-{row['raw_payload_hash'][:16]}"
        if enrollment_status is None:
            learning_status = LearningRecordStatus.NOT_STARTED
        else:
            learning_status = _to_learning_status(enrollment_status, expires_at)
        return LearningRecord(
            id=record_id,
            user_id=payload["user_id"],
            course_id=payload["course_id"],
            source_system=payload.get("source_system") or batch["source_system"],
            source_record_id=payload.get("source_record_id"),
            status=learning_status,
            assigned_date=_parse_datetime(payload.get("assigned_date")),
            due_date=_parse_date(payload.get("due_date")),
            completed_date=_parse_datetime(payload.get("completed_date")),
            completion_percentage=_parse_float(payload.get("completion_percentage")) or 0.0,
            score=_parse_float(payload.get("score")),
            expires_at=expires_at,
            raw_source_hash=row["raw_payload_hash"],
            source_payload=payload,
        )
