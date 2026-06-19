"""Trend analytics over tenant-scoped learning records.

This is the read/report half of the analytics surface (the "reporting /
analytics / Power BI" ask). It computes period-bucketed, tenant-scoped metrics
over the learning records already persisted by the audit/sync flow:

  * completion rate over time (records completed in a period vs. records due),
  * open readiness-gap counts by period (records past due and not yet completed),
  * expiring-soon counts by horizon (completions whose validity lapses next).

All of it is grouped by learning item so a manager can see which requirement is
driving the trend. Results are typed Pydantic v2 models (no ``dict[str, Any]``)
so the shape is contractual for the CLI, API, and any BI consumer downstream.

Language note: this surface reports *readiness* and *evidence*, never
"compliant"/"certified". A record that satisfies a requirement is "completed";
the absence of one is a "readiness gap". That keeps the claim boundary intact.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, Field

from complyos.core.bi_feed import BiFeed, build_bi_feed, render_bi_feed_csv
from complyos.core.repository import LocalRepository
from complyos.core.time import utc_now
from complyos.models.domain import Course, LearningRecord, LearningRecordStatus, User
from complyos.services.context import (
    PERM_ANALYTICS_READ,
    PERM_EVIDENCE_EXPORT,
    ActorContext,
    require_permission,
)


class Granularity(StrEnum):
    """Period bucket size for the time-series. Monthly is the reporting default."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"


def _period_key(value: date, granularity: Granularity) -> str:
    """Return a stable, sortable ISO period key for a date.

    Monthly -> ``YYYY-MM``; weekly -> ``YYYY-Www`` using the ISO week-year so a
    late-December week that belongs to the next ISO year buckets correctly.
    """
    if granularity is Granularity.WEEKLY:
        iso_year, iso_week, _ = value.isocalendar()
        return f"{iso_year:04d}-W{iso_week:02d}"
    return f"{value.year:04d}-{value.month:02d}"


def _as_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    return value.date() if isinstance(value, datetime) else value


class ItemPeriodMetric(BaseModel):
    """One learning item's metrics within one period bucket."""

    period: str
    course_id: str
    course_code: str
    course_title: str
    due_count: int = 0
    completed_count: int = 0
    open_gap_count: int = 0
    completion_rate: float = 0.0


class ExpiringSoonBucket(BaseModel):
    """Count of valid completions that lapse within a horizon, by learning item."""

    course_id: str
    course_code: str
    course_title: str
    expiring_count: int = 0


class TrendAnalyticsResult(BaseModel):
    """Typed, tenant-scoped trend-analytics result."""

    tenant_id: str
    granularity: Granularity
    generated_at: datetime
    as_of: date
    horizon_days: int
    periods: list[str] = Field(default_factory=list)
    item_period_metrics: list[ItemPeriodMetric] = Field(default_factory=list)
    expiring_soon: list[ExpiringSoonBucket] = Field(default_factory=list)
    total_records: int = 0
    overall_completion_rate: float = 0.0


def _is_completed(record: LearningRecord) -> bool:
    return record.status in {
        LearningRecordStatus.COMPLETED,
        LearningRecordStatus.EXEMPT,
    } or record.exempt


def _compute_trends(
    rows: list[tuple[LearningRecord, User, Course]],
    *,
    granularity: Granularity,
    as_of: date,
    horizon: date,
) -> tuple[list[ItemPeriodMetric], list[ExpiringSoonBucket], int, float]:
    """Pure period-bucketing core. Kept free of I/O so it is unit-testable.

    A record contributes to a period when it has an anchor date in that period:
    completions anchor on ``completed_date``; everything else anchors on
    ``due_date``. Open readiness gaps are records that are past due, not exempt,
    and not completed. Expiring-soon counts valid completions whose ``expires_at``
    falls in the closed window ``[as_of, horizon]``.
    """
    # (period, course_id) -> mutable counters; course meta carried alongside.
    buckets: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"due": 0, "completed": 0, "open_gap": 0}
    )
    course_meta: dict[str, Course] = {}
    expiring: dict[str, int] = defaultdict(int)
    completed_total = 0

    for record, _user, course in rows:
        course_meta[course.id] = course
        completed = _is_completed(record)
        if completed:
            completed_total += 1

        anchor = _as_date(record.completed_date) if completed else _as_date(record.due_date)
        if anchor is None:
            # Fall back to the assigned date so a record with neither a due nor a
            # completed date still lands in a period rather than vanishing.
            anchor = _as_date(record.assigned_date)
        if anchor is not None:
            key = (_period_key(anchor, granularity), course.id)
            buckets[key]["due"] += 1
            if completed:
                buckets[key]["completed"] += 1

        # Open readiness gap: past due, not exempt, not satisfied.
        due = _as_date(record.due_date)
        if not completed and due is not None and due < as_of:
            gap_anchor = _period_key(due, granularity)
            buckets[(gap_anchor, course.id)]["open_gap"] += 1

        # Expiring-soon: a valid completion whose validity lapses in the window.
        expires = record.expires_at
        if (
            not record.exempt
            and expires is not None
            and as_of <= expires <= horizon
            and record.status == LearningRecordStatus.COMPLETED
        ):
            expiring[course.id] += 1

    metrics: list[ItemPeriodMetric] = []
    for (period, course_id), counts in buckets.items():
        meta = course_meta[course_id]
        due_count = counts["due"]
        done_count = counts["completed"]
        metrics.append(
            ItemPeriodMetric(
                period=period,
                course_id=course_id,
                course_code=meta.code,
                course_title=meta.title,
                due_count=due_count,
                completed_count=done_count,
                open_gap_count=counts["open_gap"],
                completion_rate=round(done_count / due_count, 4) if due_count else 0.0,
            )
        )
    metrics.sort(key=lambda m: (m.period, m.course_code))

    expiring_buckets = [
        ExpiringSoonBucket(
            course_id=course_id,
            course_code=course_meta[course_id].code,
            course_title=course_meta[course_id].title,
            expiring_count=count,
        )
        for course_id, count in expiring.items()
    ]
    expiring_buckets.sort(key=lambda b: (-b.expiring_count, b.course_code))

    total = len(rows)
    overall_rate = round(completed_total / total, 4) if total else 0.0
    return metrics, expiring_buckets, total, overall_rate


class TrendAnalyticsService:
    """Authorization-gated, tenant-scoped trend analytics over learning records."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def compute(
        self,
        context: ActorContext,
        *,
        granularity: Granularity = Granularity.MONTHLY,
        horizon_days: int = 30,
        as_of: date | None = None,
    ) -> TrendAnalyticsResult:
        """Compute period-bucketed trend metrics for the caller's tenant.

        Tenant scope is taken from ``context.tenant_id`` — never a caller-supplied
        argument — so a report can only ever see one tenant's records. Fails closed
        for an actor without ``analytics:read``.
        """
        require_permission(context, PERM_ANALYTICS_READ)
        anchor = as_of or utc_now().date()
        horizon = anchor + timedelta(days=horizon_days)
        rows = self.repository.list_learning_records_with_owner(tenant_id=context.tenant_id)
        metrics, expiring, total, overall_rate = _compute_trends(
            rows, granularity=granularity, as_of=anchor, horizon=horizon
        )
        periods = sorted({m.period for m in metrics})
        return TrendAnalyticsResult(
            tenant_id=context.tenant_id,
            granularity=granularity,
            generated_at=utc_now(),
            as_of=anchor,
            horizon_days=horizon_days,
            periods=periods,
            item_period_metrics=metrics,
            expiring_soon=expiring,
            total_records=total,
            overall_completion_rate=overall_rate,
        )

    def bi_feed(
        self,
        context: ActorContext,
        *,
        as_of: date | None = None,
    ) -> BiFeed:
        """Build the typed, denormalized BI feed for the caller's tenant.

        Read-level (``analytics:read``) and tenant-scoped via ``context.tenant_id``;
        the actual file/content export is gated separately at ``evidence:export``.
        """
        require_permission(context, PERM_ANALYTICS_READ)
        anchor = as_of or utc_now().date()
        rows = self.repository.list_learning_records_with_owner(tenant_id=context.tenant_id)
        return build_bi_feed(
            rows,
            tenant_id=context.tenant_id,
            generated_at=utc_now(),
            as_of=anchor,
        )

    def export_bi_feed(
        self,
        context: ActorContext,
        *,
        fmt: str = "csv",
        as_of: date | None = None,
        output_path: str | None = None,
    ) -> dict[str, object]:
        """Export the BI feed as CSV or JSON content (and optionally to a file).

        Gated at ``evidence:export`` because this materializes learner-level
        evidence rows. CSV is produced through the shared safe-CSV writer so every
        learner/source-derived cell is formula-injection neutralized. When
        ``output_path`` is given the content is also written there (CLI/local use);
        remote callers get the content in the return value without a server write.
        """
        require_permission(context, PERM_EVIDENCE_EXPORT)
        if fmt not in {"csv", "json"}:
            raise ValueError(f"unsupported BI feed format: {fmt!r} (expected 'csv' or 'json')")
        feed = self.bi_feed(context, as_of=as_of)
        content = render_bi_feed_csv(feed) if fmt == "csv" else feed.model_dump_json(indent=2)
        result: dict[str, object] = {
            "format": fmt,
            "tenant_id": feed.tenant_id,
            "row_count": feed.row_count,
            "columns": feed.columns,
            "content": content,
        }
        if output_path is not None:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(content)
            result["output_path"] = output_path
        return result
