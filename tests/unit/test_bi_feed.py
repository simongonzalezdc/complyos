"""BI-feed tests: column stability, safe-CSV neutralization, tenant scoping.

The BI feed is the stable, denormalized learner x requirement export for Power BI
/ spreadsheet ingestion. Its contract: a fixed column order, formula-injection
neutralized CSV cells (reusing the existing safe-CSV writer), tenant scoping with
no cross-tenant leakage, and an evidence:export authorization gate.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime

import pytest

from complyos.core.bi_feed import BI_FEED_COLUMNS
from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    Course,
    LearningRecord,
    LearningRecordStatus,
    User,
)
from complyos.services.analytics import TrendAnalyticsService
from complyos.services.context import AuthorizationError, default_local_context

AS_OF = date(2026, 6, 15)

# Canonical CSV/Sheets formula-injection payloads; one per dangerous prefix.
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _user(uid: str, *, tenant_id: str, first: str = "Alice", dept: str = "Eng") -> User:
    return User(
        id=uid,
        employee_id=f"E-{uid}",
        email=f"{uid}@example.com",
        first_name=first,
        last_name="Learner",
        department=dept,
        region="US",
        hire_date=date(2024, 1, 1),
        custom_attributes={"tenant_id": tenant_id},
    )


def _course(cid: str, code: str, title: str) -> Course:
    return Course(id=cid, code=code, title=title, mandatory=True)


def _record(rid: str, uid: str, cid: str, status: LearningRecordStatus) -> LearningRecord:
    return LearningRecord(
        id=rid,
        user_id=uid,
        course_id=cid,
        source_system="csv",
        status=status,
        due_date=date(2026, 5, 1),
        completed_date=datetime(2026, 4, 1) if status == LearningRecordStatus.COMPLETED else None,
    )


def _service(tmp_path) -> tuple[TrendAnalyticsService, LocalRepository]:
    repo = LocalRepository(str(tmp_path / "bi.db"))
    return TrendAnalyticsService(repo), repo


def test_feed_column_order_is_stable(tmp_path) -> None:
    service, repo = _service(tmp_path)
    repo.save_user(_user("u1", tenant_id="local-default"))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    repo.save_learning_record(_record("lr1", "u1", "c1", LearningRecordStatus.COMPLETED))
    context = default_local_context(surface="cli", role="owner")

    feed = service.bi_feed(context, as_of=AS_OF)

    # The feed's declared columns are exactly the documented, ordered schema.
    assert feed.columns == list(BI_FEED_COLUMNS)
    # And the CSV header row matches it byte-for-byte in order.
    csv_text = service.export_bi_feed(context, fmt="csv")["content"]
    header = next(csv.reader(io.StringIO(csv_text)))
    assert header == list(BI_FEED_COLUMNS)


def test_csv_neutralizes_formula_injection_in_learner_fields(tmp_path) -> None:
    service, repo = _service(tmp_path)
    # A learner whose name begins with "=" is the canonical attack.
    repo.save_user(_user("u1", tenant_id="local-default", first="=2+5+cmd|' /C calc'!A0"))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    repo.save_learning_record(_record("lr1", "u1", "c1", LearningRecordStatus.COMPLETED))
    context = default_local_context(surface="cli", role="owner")

    csv_text = service.export_bi_feed(context, fmt="csv")["content"]
    rows = list(csv.reader(io.StringIO(csv_text)))
    name_idx = list(BI_FEED_COLUMNS).index("learner_name")
    learner_name = rows[1][name_idx]

    # The cell is quote-prefixed so a spreadsheet treats it as inert text.
    assert learner_name.startswith("'=")


def test_csv_neutralizes_every_dangerous_prefix(tmp_path) -> None:
    service, repo = _service(tmp_path)
    context = default_local_context(surface="cli", role="owner")
    name_idx = list(BI_FEED_COLUMNS).index("learner_name")

    for i, prefix in enumerate(DANGEROUS_PREFIXES):
        repo.save_user(
            _user(f"u{i}", tenant_id="local-default", first=f"{prefix}HYPERLINK(0)")
        )
        repo.save_course(_course(f"c{i}", f"SEC-{i}", f"Course {i}"))
        repo.save_learning_record(
            _record(f"lr{i}", f"u{i}", f"c{i}", LearningRecordStatus.COMPLETED)
        )

    csv_text = service.export_bi_feed(context, fmt="csv")["content"]
    rows = list(csv.reader(io.StringIO(csv_text)))
    for data_row in rows[1:]:
        cell = data_row[name_idx]
        # No cell may start with a live formula prefix; it must be quote-prefixed.
        assert cell.startswith("'"), f"un-neutralized cell: {cell!r}"


def test_feed_tenant_scoped_no_cross_tenant_rows(tmp_path) -> None:
    service, repo = _service(tmp_path)
    repo.save_user(_user("u-a", tenant_id="tenant-a"))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    repo.save_learning_record(_record("lr-a", "u-a", "c1", LearningRecordStatus.COMPLETED))
    repo.save_user(_user("u-b", tenant_id="tenant-b"))
    repo.save_course(_course("c2", "PRIV-201", "Privacy 201"))
    repo.save_learning_record(_record("lr-b", "u-b", "c2", LearningRecordStatus.NOT_STARTED))

    ctx_a = default_local_context(surface="api", role="owner", tenant_id="tenant-a")
    feed_a = service.bi_feed(ctx_a, as_of=AS_OF)

    assert feed_a.row_count == 1
    assert {row.learner_id for row in feed_a.rows} == {"u-a"}
    assert {row.requirement_code for row in feed_a.rows} == {"SEC-101"}


def test_readiness_state_uses_evidence_language_not_compliance_verdict(tmp_path) -> None:
    service, repo = _service(tmp_path)
    repo.save_user(_user("u1", tenant_id="local-default"))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    repo.save_learning_record(_record("lr1", "u1", "c1", LearningRecordStatus.COMPLETED))
    context = default_local_context(surface="cli", role="owner")

    feed = service.bi_feed(context, as_of=AS_OF)

    # A satisfied requirement reads as "met", never "compliant"/"certified".
    assert feed.rows[0].readiness_state == "met"
    assert feed.rows[0].readiness_state not in {"compliant", "certified"}


def test_empty_feed_has_header_only_csv(tmp_path) -> None:
    service, _repo = _service(tmp_path)
    context = default_local_context(surface="cli", role="owner")

    result = service.export_bi_feed(context, fmt="csv")
    rows = list(csv.reader(io.StringIO(str(result["content"]))))

    assert result["row_count"] == 0
    assert rows == [list(BI_FEED_COLUMNS)]


def test_export_bi_feed_requires_evidence_export_and_fails_closed(tmp_path) -> None:
    service, _repo = _service(tmp_path)
    # read_only has analytics:read but NOT evidence:export.
    context = default_local_context(surface="api", role="read_only")

    with pytest.raises(AuthorizationError) as exc:
        service.export_bi_feed(context, fmt="csv")

    assert exc.value.permission == "evidence:export"


def test_bi_feed_read_requires_analytics_read_and_fails_closed(tmp_path) -> None:
    service, _repo = _service(tmp_path)
    # importer holds neither analytics:read nor evidence:export.
    context = default_local_context(surface="api", role="importer")

    with pytest.raises(AuthorizationError) as exc:
        service.bi_feed(context)

    assert exc.value.permission == "analytics:read"


def test_unsupported_format_is_rejected(tmp_path) -> None:
    service, _repo = _service(tmp_path)
    context = default_local_context(surface="cli", role="owner")

    with pytest.raises(ValueError, match="unsupported BI feed format"):
        service.export_bi_feed(context, fmt="xml")
