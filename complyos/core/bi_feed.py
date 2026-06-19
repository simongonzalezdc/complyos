"""BI-ready, denormalized learner x requirement feed.

A flat tabular export designed for Power BI / spreadsheet ingestion: one row per
(learner, learning requirement), with a stable column order, documented columns,
and ISO-8601 dates. CSV is produced through the shared safe-CSV writer
(``write_safe_csv``) so every learner/source-derived cell is formula-injection
neutralized; JSON carries the same rows for programmatic consumers.

Claim boundary: columns describe *readiness* and *evidence* state, never
"compliant"/"certified". ``readiness_state`` is one of ``met`` / ``open`` /
``expired`` / ``exempt`` — the evidence of where a learner stands, not a legal
compliance verdict.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from complyos.core.report_exporter import write_safe_csv
from complyos.models.domain import Course, LearningRecord, LearningRecordStatus, User

# Stable, documented column order. Appending new columns at the end is safe for a
# BI consumer; reordering or renaming is a breaking change to the feed contract.
BI_FEED_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "learner_id",
    "employee_id",
    "learner_name",
    "learner_email",
    "department",
    "region",
    "requirement_id",
    "requirement_code",
    "requirement_title",
    "mandatory",
    "source_system",
    "status",
    "readiness_state",
    "completion_percentage",
    "assigned_date",
    "due_date",
    "completed_date",
    "expires_at",
    "days_overdue",
    "is_expired",
)


class BiFeedRow(BaseModel):
    """One denormalized (learner, requirement) row of the BI feed."""

    tenant_id: str
    learner_id: str
    employee_id: str
    learner_name: str
    learner_email: str
    department: str
    region: str
    requirement_id: str
    requirement_code: str
    requirement_title: str
    mandatory: bool
    source_system: str
    status: str
    readiness_state: str
    completion_percentage: float
    assigned_date: str | None = None
    due_date: str | None = None
    completed_date: str | None = None
    expires_at: str | None = None
    days_overdue: int | None = None
    is_expired: bool = False


class BiFeed(BaseModel):
    """Typed BI feed envelope: stable column order plus the denormalized rows."""

    tenant_id: str
    generated_at: datetime
    as_of: date
    columns: list[str] = Field(default_factory=lambda: list(BI_FEED_COLUMNS))
    row_count: int = 0
    rows: list[BiFeedRow] = Field(default_factory=list)


def _iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _readiness_state(record: LearningRecord, *, as_of: date) -> str:
    """Map a record to its readiness state (not a compliance verdict)."""
    if record.exempt or record.status == LearningRecordStatus.EXEMPT:
        return "exempt"
    if record.is_expired(as_of):
        return "expired"
    if record.status == LearningRecordStatus.COMPLETED:
        return "met"
    return "open"


def _days_overdue(record: LearningRecord, *, as_of: date) -> int | None:
    if record.due_date is None or record.due_date >= as_of:
        return None
    if record.status == LearningRecordStatus.COMPLETED or record.exempt:
        return None
    return (as_of - record.due_date).days


def build_bi_feed(
    rows: list[tuple[LearningRecord, User, Course]],
    *,
    tenant_id: str,
    generated_at: datetime,
    as_of: date,
) -> BiFeed:
    """Build the typed BI feed from tenant-scoped (record, user, course) rows.

    Rows are sorted by (learner_id, requirement_code) so the feed is stable
    across runs for the same underlying data — a BI consumer can diff snapshots.
    """
    feed_rows = [
        BiFeedRow(
            tenant_id=tenant_id,
            learner_id=user.id,
            employee_id=user.employee_id,
            learner_name=user.full_name,
            learner_email=user.email,
            department=user.department,
            region=user.region,
            requirement_id=course.id,
            requirement_code=course.code,
            requirement_title=course.title,
            mandatory=course.mandatory,
            source_system=record.source_system,
            status=record.status.value,
            readiness_state=_readiness_state(record, as_of=as_of),
            completion_percentage=record.completion_percentage,
            assigned_date=_iso(record.assigned_date),
            due_date=_iso(record.due_date),
            completed_date=_iso(record.completed_date),
            expires_at=_iso(record.expires_at),
            days_overdue=_days_overdue(record, as_of=as_of),
            is_expired=record.is_expired(as_of),
        )
        for record, user, course in rows
    ]
    feed_rows.sort(key=lambda r: (r.learner_id, r.requirement_code))
    return BiFeed(
        tenant_id=tenant_id,
        generated_at=generated_at,
        as_of=as_of,
        row_count=len(feed_rows),
        rows=feed_rows,
    )


def render_bi_feed_csv(feed: BiFeed) -> str:
    """Render the BI feed to a safe CSV string (formula-injection neutralized)."""
    return write_safe_csv(
        list(BI_FEED_COLUMNS),
        [row.model_dump() for row in feed.rows],
    )
