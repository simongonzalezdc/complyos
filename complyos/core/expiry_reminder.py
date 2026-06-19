"""Forward-looking expiry reminders: which records expire *soon* (not yet expired).

The auditor (``complyos/core/auditor.py``) answers "who is already out of
compliance". The compliance digest (``complyos/core/digest.py``) answers "what
changed since last run". Neither is proactive about a recertification that is
*about* to lapse. This module computes that forward-looking set: learning
records whose ``expires_at`` falls inside a configurable window (default 30/60/90
days) and has not yet passed.

The output is typed end-to-end (Pydantic v2) so the notification payload that
reaches the outbox carries a known shape, not a free-form ``dict[str, Any]``.
Records under an active legal hold are excluded by the caller before grouping —
a held subject's data must not be churned into outbound reminders.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from complyos.models.domain import Course, LearningRecord, User

# Default reminder windows in days. Each window is a *threshold*: a record is
# bucketed into the smallest (most urgent) window whose horizon still contains
# its expiry, so a record expiring in 20 days lands in the 30-day reminder, not
# also in 60/90. Ordering smallest-first is load-bearing for that bucketing.
DEFAULT_EXPIRY_WINDOWS_DAYS: tuple[int, ...] = (30, 60, 90)


class ExpiringRecordEntry(BaseModel):
    """One learner/item recertification that is approaching expiry."""

    learning_record_id: str
    user_id: str
    user_name: str
    user_email: str
    department: str
    course_code: str
    course_title: str
    expires_at: date
    days_until_expiry: int


class ExpiringWindowGroup(BaseModel):
    """All records expiring within a single reminder window."""

    window_days: int
    count: int
    entries: list[ExpiringRecordEntry] = Field(default_factory=list)


class ExpiringSoonReminder(BaseModel):
    """Typed payload enqueued to the notification outbox for one tenant.

    This is the model whose ``model_dump`` becomes the outbox event payload, so
    its fields define the reminder contract. ``summary``/``email_subject`` mirror
    the keys the existing email/webhook senders already read.
    """

    tenant_id: str
    generated_at: date
    windows_days: list[int]
    total_expiring: int
    groups: list[ExpiringWindowGroup] = Field(default_factory=list)
    summary: str = ""
    email_subject: str = "ComplyOS: certifications expiring soon"


def _entry_from_record(
    record: LearningRecord,
    user: User,
    course: Course,
    *,
    as_of: date,
) -> ExpiringRecordEntry:
    # expires_at is guaranteed non-None by the repository query, but assert the
    # invariant locally so a future caller cannot feed an open-ended record in.
    if record.expires_at is None:  # pragma: no cover - defensive guard
        raise ValueError("expiring record must carry expires_at")
    return ExpiringRecordEntry(
        learning_record_id=record.id,
        user_id=user.id,
        user_name=user.full_name,
        user_email=user.email,
        department=user.department,
        course_code=course.code,
        course_title=course.title,
        expires_at=record.expires_at,
        days_until_expiry=(record.expires_at - as_of).days,
    )


def build_expiring_soon_reminder(
    *,
    tenant_id: str,
    records: list[tuple[LearningRecord, User, Course]],
    windows_days: list[int],
    as_of: date,
) -> ExpiringSoonReminder:
    """Bucket already-fetched, not-yet-expired records into reminder windows.

    Each record is placed in the smallest window whose ``as_of + window`` horizon
    still covers its expiry date, so windows do not double-count. Records outside
    every window (expiring later than the largest window) are dropped. Legal-hold
    filtering is the caller's responsibility and happens before this call.
    """
    sorted_windows = sorted({int(w) for w in windows_days})
    if not sorted_windows:
        raise ValueError("at least one reminder window (in days) is required")

    buckets: dict[int, list[ExpiringRecordEntry]] = {w: [] for w in sorted_windows}
    for record, user, course in records:
        if record.expires_at is None or record.expires_at < as_of:
            continue
        days_left = (record.expires_at - as_of).days
        chosen = next((w for w in sorted_windows if days_left <= w), None)
        if chosen is None:
            continue
        buckets[chosen].append(_entry_from_record(record, user, course, as_of=as_of))

    groups = [
        ExpiringWindowGroup(
            window_days=window,
            count=len(buckets[window]),
            entries=sorted(buckets[window], key=lambda e: (e.days_until_expiry, e.user_email)),
        )
        for window in sorted_windows
    ]
    total = sum(group.count for group in groups)
    window_label = "/".join(str(w) for w in sorted_windows)
    return ExpiringSoonReminder(
        tenant_id=tenant_id,
        generated_at=as_of,
        windows_days=sorted_windows,
        total_expiring=total,
        groups=groups,
        summary=(
            f"{total} certification(s) expiring within {window_label} days "
            f"for tenant {tenant_id}."
        ),
    )
