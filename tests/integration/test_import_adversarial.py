"""Adversarial import integration tests (plan §6.5 / §13.3).

Exercises ImportService end-to-end against a real LocalRepository to prove the
gated lifecycle fails closed on the documented attack/failure cases:
stale export, partial load, duplicate identity, backdated due/expiry dates, and
re-promote idempotency. Each invariant is asserted at the service boundary, the
same boundary every surface (API/CLI/MCP) flows through.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.imports import ImportPreviewRequest, ImportService

GOOD_CSV = (
    "user_id,course_id,status,source_record_id\n"
    "u1,c1,completed,sr1\n"
    "u2,c2,in_progress,sr2\n"
)


def _service(tmp_path, name: str) -> tuple[ImportService, object]:
    repo = LocalRepository(str(tmp_path / name))
    return ImportService(repo), repo


def _context():
    return default_local_context(surface="cli")


def test_stale_export_is_flagged_and_blocks_promotion(tmp_path) -> None:
    """A source export older than the freshness policy is surfaced as STALE_EXPORT
    and gates every row to NEEDS_DECISION so it cannot promote silently."""
    service, repo = _service(tmp_path, "stale.db")
    context = _context()
    stale_export_at = datetime.now(UTC) - timedelta(days=90)

    preview = service.preview(
        context,
        ImportPreviewRequest(
            csv_text=GOOD_CSV,
            source_exported_at=stale_export_at,
            max_export_age_days=14,
        ),
    )

    assert any(issue.code == "STALE_EXPORT" for issue in preview.issues)
    assert preview.can_promote is False
    result = service.promote(context, preview.batch_id)
    assert result.status == "QUARANTINED"
    assert result.blocked_rows > 0
    assert repo.list_learning_records() == []


def test_empty_csv_is_a_partial_load_and_cannot_promote(tmp_path) -> None:
    """A declared import with no data rows is a partial load: PARTIAL_LOAD is
    raised and promotion is impossible without an explicit operator decision."""
    service, repo = _service(tmp_path, "partial.db")
    context = _context()

    preview = service.preview(
        context,
        ImportPreviewRequest(csv_text="user_id,course_id,status\n"),
    )

    assert any(issue.code == "PARTIAL_LOAD" for issue in preview.issues)
    assert preview.can_promote is False
    result = service.promote(context, preview.batch_id)
    assert result.status == "QUARANTINED"
    assert repo.list_learning_records() == []


def test_duplicate_learner_ids_need_decision_and_block_promotion(tmp_path) -> None:
    """Duplicate learner/course/source identities enter NEEDS_DECISION; the batch
    cannot promote until the duplicate is resolved with an explicit decision."""
    service, repo = _service(tmp_path, "dupe.db")
    context = _context()
    dup_csv = (
        "user_id,course_id,status,source_record_id\n"
        "u1,c1,completed,sr1\n"
        "u1,c1,completed,sr1\n"
    )

    preview = service.preview(context, ImportPreviewRequest(csv_text=dup_csv))

    assert any(issue.code == "DUPLICATE_ROW" for issue in preview.issues)
    assert preview.row_counts.get("NEEDS_DECISION", 0) >= 1
    assert preview.can_promote is False
    blocked = service.promote(context, preview.batch_id)
    assert blocked.status == "QUARANTINED"
    assert repo.list_learning_records() == []


def test_backdated_due_date_is_flagged_and_needs_decision(tmp_path) -> None:
    """A due date already in the past is an anomaly that could mask an open gap;
    the row is flagged BACKDATED_DATE and routed to the reviewer queue."""
    service, repo = _service(tmp_path, "backdated-due.db")
    context = _context()
    backdated_csv = (
        "user_id,course_id,status,due_date\n"
        "u1,c1,not_started,2000-01-01\n"
    )

    preview = service.preview(context, ImportPreviewRequest(csv_text=backdated_csv))

    assert any(issue.code == "BACKDATED_DATE" for issue in preview.issues)
    assert preview.row_counts.get("NEEDS_DECISION", 0) == 1
    assert preview.can_promote is False
    result = service.promote(context, preview.batch_id)
    assert result.status == "QUARANTINED"
    assert repo.list_learning_records() == []


def test_expiry_before_assignment_is_flagged_and_needs_decision(tmp_path) -> None:
    """An expiry date that precedes its own assignment date is anomalous (it would
    import as already-expired); flagged BACKDATED_DATE for reviewer decision."""
    service, repo = _service(tmp_path, "backdated-expiry.db")
    context = _context()
    csv_text = (
        "user_id,course_id,status,assigned_date,expires_at\n"
        "u1,c1,completed,2026-01-01,2025-01-01\n"
    )

    preview = service.preview(context, ImportPreviewRequest(csv_text=csv_text))

    backdated = [i for i in preview.issues if i.code == "BACKDATED_DATE"]
    assert backdated and backdated[0].column == "expires_at"
    assert preview.can_promote is False


def test_clean_future_dates_do_not_trip_the_backdated_flag(tmp_path) -> None:
    """Guard against false positives: a future due date and a normal forward
    assignment->expiry ordering must NOT be flagged, so the row stays promotable."""
    service, _repo = _service(tmp_path, "future-dates.db")
    context = _context()
    future_due = (datetime.now(UTC) + timedelta(days=365)).date().isoformat()
    csv_text = (
        "user_id,course_id,status,due_date,assigned_date,expires_at\n"
        f"u1,c1,completed,{future_due},2026-01-01,2027-01-01\n"
    )

    preview = service.preview(context, ImportPreviewRequest(csv_text=csv_text))

    assert not any(issue.code == "BACKDATED_DATE" for issue in preview.issues)
    assert preview.can_promote is True


def test_re_promote_same_batch_is_idempotent(tmp_path) -> None:
    """Re-uploading the identical file returns the same batch (idempotency key),
    and promoting the same batch twice does not duplicate learning records."""
    service, repo = _service(tmp_path, "idempotent.db")
    context = _context()

    first_preview = service.preview(context, ImportPreviewRequest(csv_text=GOOD_CSV))
    second_preview = service.preview(context, ImportPreviewRequest(csv_text=GOOD_CSV))
    assert first_preview.batch_id == second_preview.batch_id

    first_promote = service.promote(context, first_preview.batch_id)
    assert first_promote.status == "PROMOTED"
    records_after_first = len(repo.list_learning_records())
    assert records_after_first == 2

    # Re-promoting the same batch is a no-op that returns PROMOTED without
    # creating duplicate learning records.
    second_promote = service.promote(context, first_preview.batch_id)
    assert second_promote.status == "PROMOTED"
    assert len(repo.list_learning_records()) == records_after_first


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
