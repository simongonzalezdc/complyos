"""Tests for the gated import lifecycle."""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.imports import ImportPreviewRequest, ImportService

GOOD_CSV = (
    "user_id,course_id,status,source_record_id\n"
    "u1,c1,completed,sr1\n"
    "u2,c2,in_progress,sr2\n"
)
BAD_CSV = (
    "tenant_id,user_id,course_id,status,extra\n"
    "other-tenant,=cmd,c1,completed,secret\n"
    "local-default,u1,c1,completed,secret\n"
    "local-default,u1,c1,completed,secret\n"
)


def test_preview_good_csv_can_promote_and_is_idempotent(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "imports.db"))
    service = ImportService(repo)
    context = default_local_context(surface="cli")

    first = service.preview(context, ImportPreviewRequest(csv_text=GOOD_CSV))
    second = service.preview(context, ImportPreviewRequest(csv_text=GOOD_CSV))

    assert first.batch_id == second.batch_id
    assert first.status == "QUARANTINED"
    assert first.can_promote is True
    assert first.row_counts["VALID"] == 2


def test_bad_csv_fails_closed_and_does_not_promote(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "bad-imports.db"))
    service = ImportService(repo)
    context = default_local_context(surface="cli")

    preview = service.preview(context, ImportPreviewRequest(csv_text=BAD_CSV))
    result = service.promote(context, preview.batch_id)

    assert preview.can_promote is False
    assert any(issue.code == "FORMULA_INJECTION" for issue in preview.issues)
    assert any(issue.code == "UNEXPECTED_COLUMN" for issue in preview.issues)
    assert any(issue.code == "MIXED_TENANT" for issue in preview.issues)
    assert any(issue.code == "DUPLICATE_ROW" for issue in preview.issues)
    assert result.status == "QUARANTINED"
    assert result.blocked_rows > 0
    assert repo.list_learning_records() == []


def test_explicit_decision_can_accept_needs_decision_row(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "decision.db"))
    service = ImportService(repo)
    context = default_local_context(surface="cli")

    preview = service.preview(
        context,
        ImportPreviewRequest(csv_text="user_id,course_id,status,extra\nu1,c1,completed,note\n"),
    )
    row = repo.list_import_rows(preview.batch_id)[0]
    decision = service.decide(
        context,
        batch_id=preview.batch_id,
        row_id=row["id"],
        decision_type="accept",
        reason="extra column reviewed",
    )

    assert decision.row_status == "VALID"
    assert service.promote(context, preview.batch_id).status == "PROMOTED"


def test_promote_good_csv_writes_records_and_evidence(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "promote.db"))
    service = ImportService(repo)
    context = default_local_context(surface="cli")

    preview = service.preview(context, ImportPreviewRequest(csv_text=GOOD_CSV))
    result = service.promote(context, preview.batch_id)

    records = repo.list_learning_records(source_system="csv")
    evidence = repo.list_evidence_ledger()

    assert result.status == "PROMOTED"
    assert result.promoted_rows == 2
    assert result.evidence_id is not None
    assert len(records) == 2
    assert evidence[0]["query_type"] == "import.promote"
