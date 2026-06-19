"""Trend-analytics service tests: bucketing, tenant scoping, authz, empties.

The analytics surface is the read/report half of the "reporting / analytics /
Power BI" ask. It must: bucket records across multiple periods correctly, never
leak one tenant's records into another's report, fail closed for an actor without
analytics:read, and degrade cleanly to an empty result on empty data.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    Course,
    LearningRecord,
    LearningRecordStatus,
    User,
)
from complyos.services.analytics import Granularity, TrendAnalyticsService
from complyos.services.context import AuthorizationError, default_local_context

AS_OF = date(2026, 6, 15)


def _user(uid: str, *, tenant_id: str, dept: str = "Eng") -> User:
    return User(
        id=uid,
        employee_id=f"E-{uid}",
        email=f"{uid}@example.com",
        first_name=uid.upper(),
        last_name="Learner",
        department=dept,
        region="US",
        hire_date=date(2024, 1, 1),
        custom_attributes={"tenant_id": tenant_id},
    )


def _course(cid: str, code: str, title: str, *, mandatory: bool = True) -> Course:
    return Course(id=cid, code=code, title=title, mandatory=mandatory)


def _seed_two_period_tenant(repo: LocalRepository, *, tenant_id: str) -> None:
    """Seed one tenant with records completed in two distinct months."""
    repo.save_user(_user("u1", tenant_id=tenant_id))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    # Completed in April (one month) and May (another) -> two period buckets.
    repo.save_learning_record(
        LearningRecord(
            id=f"{tenant_id}-lr-apr",
            user_id="u1",
            course_id="c1",
            source_system="csv",
            status=LearningRecordStatus.COMPLETED,
            due_date=date(2026, 4, 10),
            completed_date=datetime(2026, 4, 5),
        )
    )
    repo.save_learning_record(
        LearningRecord(
            id=f"{tenant_id}-lr-may",
            user_id="u1",
            course_id="c1",
            source_system="csv",
            status=LearningRecordStatus.COMPLETED,
            due_date=date(2026, 5, 10),
            completed_date=datetime(2026, 5, 5),
        )
    )


def _service(tmp_path) -> tuple[TrendAnalyticsService, LocalRepository]:
    repo = LocalRepository(str(tmp_path / "analytics.db"))
    return TrendAnalyticsService(repo), repo


def test_records_across_periods_bucket_separately(tmp_path) -> None:
    service, repo = _service(tmp_path)
    _seed_two_period_tenant(repo, tenant_id="local-default")
    context = default_local_context(surface="cli", role="owner")

    result = service.compute(context, granularity=Granularity.MONTHLY, as_of=AS_OF)

    assert result.total_records == 2
    # Two completed records anchored in two distinct months -> two periods.
    assert set(result.periods) == {"2026-04", "2026-05"}
    by_period = {m.period: m for m in result.item_period_metrics}
    assert by_period["2026-04"].completed_count == 1
    assert by_period["2026-05"].completed_count == 1
    # Both records are completed -> overall completion rate is 1.0.
    assert result.overall_completion_rate == 1.0


def test_weekly_granularity_uses_iso_week_keys(tmp_path) -> None:
    service, repo = _service(tmp_path)
    _seed_two_period_tenant(repo, tenant_id="local-default")
    context = default_local_context(surface="cli", role="owner")

    result = service.compute(context, granularity=Granularity.WEEKLY, as_of=AS_OF)

    assert all("-W" in period for period in result.periods)


def test_open_gap_counts_past_due_unfinished_record(tmp_path) -> None:
    service, repo = _service(tmp_path)
    repo.save_user(_user("u1", tenant_id="local-default"))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    # Past due, not started -> an open readiness gap.
    repo.save_learning_record(
        LearningRecord(
            id="lr-overdue",
            user_id="u1",
            course_id="c1",
            source_system="csv",
            status=LearningRecordStatus.NOT_STARTED,
            due_date=date(2026, 5, 1),
        )
    )
    context = default_local_context(surface="cli", role="owner")

    result = service.compute(context, granularity=Granularity.MONTHLY, as_of=AS_OF)

    open_gaps = sum(m.open_gap_count for m in result.item_period_metrics)
    assert open_gaps == 1
    assert result.overall_completion_rate == 0.0


def test_expiring_soon_counts_completion_within_horizon(tmp_path) -> None:
    service, repo = _service(tmp_path)
    repo.save_user(_user("u1", tenant_id="local-default"))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    repo.save_learning_record(
        LearningRecord(
            id="lr-expiring",
            user_id="u1",
            course_id="c1",
            source_system="csv",
            status=LearningRecordStatus.COMPLETED,
            completed_date=datetime(2026, 1, 1),
            expires_at=date(2026, 6, 30),  # within a 30-day horizon of AS_OF
        )
    )
    context = default_local_context(surface="cli", role="owner")

    result = service.compute(
        context, granularity=Granularity.MONTHLY, horizon_days=30, as_of=AS_OF
    )

    assert len(result.expiring_soon) == 1
    assert result.expiring_soon[0].expiring_count == 1
    assert result.expiring_soon[0].course_code == "SEC-101"


def test_expiring_soon_excludes_completion_outside_horizon(tmp_path) -> None:
    service, repo = _service(tmp_path)
    repo.save_user(_user("u1", tenant_id="local-default"))
    repo.save_course(_course("c1", "SEC-101", "Security Basics"))
    repo.save_learning_record(
        LearningRecord(
            id="lr-far",
            user_id="u1",
            course_id="c1",
            source_system="csv",
            status=LearningRecordStatus.COMPLETED,
            completed_date=datetime(2026, 1, 1),
            expires_at=date(2026, 12, 31),  # well past a 30-day horizon
        )
    )
    context = default_local_context(surface="cli", role="owner")

    result = service.compute(
        context, granularity=Granularity.MONTHLY, horizon_days=30, as_of=AS_OF
    )

    assert result.expiring_soon == []


def test_tenant_scoping_no_cross_tenant_leakage(tmp_path) -> None:
    service, repo = _service(tmp_path)
    _seed_two_period_tenant(repo, tenant_id="tenant-a")
    # A second tenant's user must reuse a distinct id (employee_id is unique).
    repo.save_user(_user("u2", tenant_id="tenant-b"))
    repo.save_course(_course("c2", "PRIV-201", "Privacy 201"))
    repo.save_learning_record(
        LearningRecord(
            id="tenant-b-lr",
            user_id="u2",
            course_id="c2",
            source_system="csv",
            status=LearningRecordStatus.COMPLETED,
            completed_date=datetime(2026, 5, 5),
        )
    )

    ctx_a = default_local_context(surface="api", role="owner", tenant_id="tenant-a")
    ctx_b = default_local_context(surface="api", role="owner", tenant_id="tenant-b")

    result_a = service.compute(ctx_a, as_of=AS_OF)
    result_b = service.compute(ctx_b, as_of=AS_OF)

    # Tenant A sees only its 2 records; tenant B sees only its 1.
    assert result_a.total_records == 2
    assert result_b.total_records == 1
    a_codes = {m.course_code for m in result_a.item_period_metrics}
    b_codes = {m.course_code for m in result_b.item_period_metrics}
    assert a_codes == {"SEC-101"}
    assert b_codes == {"PRIV-201"}


def test_empty_data_returns_empty_result(tmp_path) -> None:
    service, _repo = _service(tmp_path)
    context = default_local_context(surface="cli", role="owner")

    result = service.compute(context, as_of=AS_OF)

    assert result.total_records == 0
    assert result.periods == []
    assert result.item_period_metrics == []
    assert result.expiring_soon == []
    assert result.overall_completion_rate == 0.0


def test_compute_requires_analytics_read_and_fails_closed(tmp_path) -> None:
    service, repo = _service(tmp_path)
    _seed_two_period_tenant(repo, tenant_id="local-default")
    # importer holds neither audit:read nor analytics:read.
    context = default_local_context(surface="api", role="importer")

    with pytest.raises(AuthorizationError) as exc:
        service.compute(context, as_of=AS_OF)

    assert exc.value.permission == "analytics:read"
