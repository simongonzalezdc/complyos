"""Pure bucketing logic for the forward-looking expiry reminder builder.

These exercise ``build_expiring_soon_reminder`` directly (no DB) for the window
edge cases — empty-window rejection, ordering, and dropping records past the
largest window — that are easiest to pin down at the unit level.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from complyos.core.expiry_reminder import build_expiring_soon_reminder
from complyos.models.domain import Course, LearningRecord, User

AS_OF = date(2026, 6, 1)


def _triple(user_id: str, days_to_expiry: int) -> tuple[LearningRecord, User, Course]:
    user = User(
        id=user_id,
        employee_id=f"E-{user_id}",
        email=f"{user_id}@example.com",
        first_name=user_id,
        last_name="L",
        department="Ops",
        region="US",
        hire_date=date(2024, 1, 1),
    )
    course = Course(id="c1", code="C1", title="Cert", mandatory=True)
    record = LearningRecord(
        id=f"lr-{user_id}",
        user_id=user_id,
        course_id="c1",
        source_system="csv",
        expires_at=AS_OF + timedelta(days=days_to_expiry),
    )
    return record, user, course


def test_empty_windows_rejected() -> None:
    with pytest.raises(ValueError, match="at least one reminder window"):
        build_expiring_soon_reminder(
            tenant_id="t", records=[], windows_days=[], as_of=AS_OF
        )


def test_records_past_largest_window_are_dropped() -> None:
    reminder = build_expiring_soon_reminder(
        tenant_id="t",
        records=[_triple("near", 10), _triple("far", 95)],
        windows_days=[30, 60, 90],
        as_of=AS_OF,
    )
    assert reminder.total_expiring == 1
    ids = {e.learning_record_id for g in reminder.groups for e in g.entries}
    assert ids == {"lr-near"}


def test_windows_are_deduped_and_sorted() -> None:
    reminder = build_expiring_soon_reminder(
        tenant_id="t",
        records=[_triple("a", 5)],
        windows_days=[90, 30, 30, 60],
        as_of=AS_OF,
    )
    assert reminder.windows_days == [30, 60, 90]


def test_entries_sorted_by_days_until_expiry() -> None:
    reminder = build_expiring_soon_reminder(
        tenant_id="t",
        records=[_triple("later", 25), _triple("sooner", 5)],
        windows_days=[30],
        as_of=AS_OF,
    )
    entries = reminder.groups[0].entries
    assert [e.learning_record_id for e in entries] == ["lr-sooner", "lr-later"]
    assert reminder.generated_at == AS_OF
