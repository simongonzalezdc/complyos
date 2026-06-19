"""Proactive upcoming-expiry reminder service (forward-looking, not-yet-expired).

Counterpart to the auditor's already-expired gaps. Covers window-boundary
correctness, already-expired exclusion, legal-hold exclusion, notification
preference suppression, tenant scoping, and that the path ENQUEUES (it never
sends directly).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.models.domain import Course, LearningRecord, LearningRecordStatus, User
from complyos.services.context import default_local_context
from complyos.services.notifications import NotificationOutboxService

# A fixed reference date keeps window-boundary assertions deterministic; the
# service accepts an ``as_of`` override exactly so the clock cannot make the
# 29-vs-31-day boundary flaky.
AS_OF = date(2026, 6, 1)


def _seed_user(repo: LocalRepository, *, user_id: str, tenant_id: str) -> None:
    repo.save_user(
        User(
            id=user_id,
            employee_id=f"E-{user_id}",
            email=f"{user_id}@example.com",
            first_name=user_id.upper(),
            last_name="Learner",
            department="Safety",
            region="US",
            hire_date=date(2024, 1, 1),
            custom_attributes={"tenant_id": tenant_id},
        )
    )


def _seed_course(repo: LocalRepository, *, course_id: str = "c1") -> None:
    repo.save_course(
        Course(id=course_id, code=course_id.upper(), title=f"{course_id} Cert", mandatory=True)
    )


def _seed_record(
    repo: LocalRepository,
    *,
    record_id: str,
    user_id: str,
    expires_at: date | None,
    course_id: str = "c1",
    exempt: bool = False,
    status: LearningRecordStatus = LearningRecordStatus.COMPLETED,
) -> None:
    repo.save_learning_record(
        LearningRecord(
            id=record_id,
            user_id=user_id,
            course_id=course_id,
            source_system="csv",
            status=status,
            exempt=exempt,
            expires_at=expires_at,
        )
    )


def test_window_boundary_includes_29_excludes_31_for_30_day_window(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-window.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="inside", tenant_id="tenant-a")
    _seed_user(repo, user_id="outside", tenant_id="tenant-a")
    _seed_record(
        repo, record_id="lr-29", user_id="inside", expires_at=AS_OF + timedelta(days=29)
    )
    _seed_record(
        repo, record_id="lr-31", user_id="outside", expires_at=AS_OF + timedelta(days=31)
    )

    reminder = service.compute_expiring_soon(context, windows_days=[30], as_of=AS_OF)

    assert reminder.total_expiring == 1
    entry_ids = {
        entry.learning_record_id for group in reminder.groups for entry in group.entries
    }
    assert entry_ids == {"lr-29"}


def test_window_boundary_is_inclusive_at_exactly_30_days(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-exact.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="exact", tenant_id="tenant-a")
    # Boundary is the closed interval [as_of, as_of + window]: a record expiring
    # in exactly 30 days IS reminded (<= window), not dropped.
    _seed_record(
        repo, record_id="lr-30", user_id="exact", expires_at=AS_OF + timedelta(days=30)
    )

    reminder = service.compute_expiring_soon(context, windows_days=[30], as_of=AS_OF)

    assert reminder.total_expiring == 1
    assert reminder.groups[0].window_days == 30
    assert reminder.groups[0].entries[0].days_until_expiry == 30


def test_already_expired_and_exempt_records_are_excluded(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-excluded.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="expired", tenant_id="tenant-a")
    _seed_user(repo, user_id="exempt", tenant_id="tenant-a")
    _seed_user(repo, user_id="soon", tenant_id="tenant-a")
    # Already expired yesterday — the auditor's job, not a proactive reminder.
    _seed_record(
        repo, record_id="lr-expired", user_id="expired", expires_at=AS_OF - timedelta(days=1)
    )
    # Exempt records never recertify, so they are not reminded even if dated.
    _seed_record(
        repo,
        record_id="lr-exempt",
        user_id="exempt",
        expires_at=AS_OF + timedelta(days=10),
        exempt=True,
    )
    _seed_record(
        repo, record_id="lr-soon", user_id="soon", expires_at=AS_OF + timedelta(days=10)
    )

    reminder = service.compute_expiring_soon(context, windows_days=[30], as_of=AS_OF)

    entry_ids = {
        entry.learning_record_id for group in reminder.groups for entry in group.entries
    }
    assert entry_ids == {"lr-soon"}


def test_records_bucket_into_smallest_matching_window(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-buckets.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    for user_id, days in (("d20", 20), ("d50", 50), ("d80", 80), ("d120", 120)):
        _seed_user(repo, user_id=user_id, tenant_id="tenant-a")
        _seed_record(
            repo,
            record_id=f"lr-{user_id}",
            user_id=user_id,
            expires_at=AS_OF + timedelta(days=days),
        )

    reminder = service.compute_expiring_soon(
        context, windows_days=[30, 60, 90], as_of=AS_OF
    )

    by_window = {group.window_days: group for group in reminder.groups}
    # 20d -> 30 window, 50d -> 60 window, 80d -> 90 window, 120d -> beyond all -> dropped.
    assert reminder.total_expiring == 3
    assert {e.learning_record_id for e in by_window[30].entries} == {"lr-d20"}
    assert {e.learning_record_id for e in by_window[60].entries} == {"lr-d50"}
    assert {e.learning_record_id for e in by_window[90].entries} == {"lr-d80"}


def test_legal_hold_excludes_subject_records(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-hold.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="held", tenant_id="tenant-a")
    _seed_user(repo, user_id="free", tenant_id="tenant-a")
    _seed_record(
        repo, record_id="lr-held", user_id="held", expires_at=AS_OF + timedelta(days=10)
    )
    _seed_record(
        repo, record_id="lr-free", user_id="free", expires_at=AS_OF + timedelta(days=10)
    )
    repo.save_legal_hold(
        {
            "id": "hold-1",
            "tenant_id": "tenant-a",
            "subject_id": "held",
            "scope": "subject",
            "reason": "litigation",
            "created_by": "privacy-admin",
        }
    )

    reminder = service.compute_expiring_soon(context, windows_days=[30], as_of=AS_OF)

    entry_ids = {
        entry.learning_record_id for group in reminder.groups for entry in group.entries
    }
    assert entry_ids == {"lr-free"}


def test_tenant_wide_legal_hold_suppresses_all_records(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-hold-wide.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="anyone", tenant_id="tenant-a")
    _seed_record(
        repo, record_id="lr-any", user_id="anyone", expires_at=AS_OF + timedelta(days=10)
    )
    repo.save_legal_hold(
        {
            "id": "hold-tenant",
            "tenant_id": "tenant-a",
            "subject_id": None,
            "scope": "tenant",
            "reason": "tenant freeze",
            "created_by": "privacy-admin",
        }
    )

    reminder = service.compute_expiring_soon(context, windows_days=[30], as_of=AS_OF)

    assert reminder.total_expiring == 0


def test_tenant_scoping_no_cross_tenant_leakage(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-tenant.db"))
    service = NotificationOutboxService(repo)

    _seed_course(repo)
    _seed_user(repo, user_id="u-a", tenant_id="tenant-a")
    _seed_user(repo, user_id="u-b", tenant_id="tenant-b")
    _seed_record(
        repo, record_id="lr-a", user_id="u-a", expires_at=AS_OF + timedelta(days=10)
    )
    _seed_record(
        repo, record_id="lr-b", user_id="u-b", expires_at=AS_OF + timedelta(days=10)
    )

    reminder_a = service.compute_expiring_soon(
        default_local_context(tenant_id="tenant-a", role="compliance_manager"),
        windows_days=[30],
        as_of=AS_OF,
    )
    reminder_b = service.compute_expiring_soon(
        default_local_context(tenant_id="tenant-b", role="compliance_manager"),
        windows_days=[30],
        as_of=AS_OF,
    )

    assert {e.learning_record_id for g in reminder_a.groups for e in g.entries} == {"lr-a"}
    assert {e.learning_record_id for g in reminder_b.groups for e in g.entries} == {"lr-b"}


def test_enqueue_creates_pending_deliveries_not_direct_send(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-enqueue.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="soon", tenant_id="tenant-a")
    _seed_record(
        repo, record_id="lr-soon", user_id="soon", expires_at=AS_OF + timedelta(days=10)
    )

    event = service.enqueue_expiring_soon_reminder(
        context, windows_days=[30], channels=["slack", "teams"], as_of=AS_OF
    )

    assert event is not None
    assert event["event_type"] == "learning.recertification_expiring_soon"
    assert event["object_type"] == "expiring_soon_reminder"
    # ENQUEUED: per-channel pending delivery rows exist, awaiting the outbox drain.
    pending = service.list_pending_deliveries(context)
    assert {delivery["channel"] for delivery in pending} == {"slack", "teams"}
    assert {delivery["status"] for delivery in pending} == {"pending"}
    # The typed payload survived into the stored event (PII redaction keeps names).
    assert event["payload"]["total_expiring"] == 1


def test_enqueue_returns_none_when_nothing_expiring(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-empty.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="far", tenant_id="tenant-a")
    _seed_record(
        repo, record_id="lr-far", user_id="far", expires_at=AS_OF + timedelta(days=200)
    )

    event = service.enqueue_expiring_soon_reminder(
        context, windows_days=[30], channels=["slack"], as_of=AS_OF
    )

    assert event is None
    assert service.list_pending_deliveries(context) == []


def test_notification_preferences_suppress_reminder_channel(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-prefs.db"))
    service = NotificationOutboxService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    _seed_course(repo)
    _seed_user(repo, user_id="soon", tenant_id="tenant-a")
    _seed_record(
        repo, record_id="lr-soon", user_id="soon", expires_at=AS_OF + timedelta(days=10)
    )
    service.set_preference(
        context,
        channel="slack",
        event_type="learning.recertification_expiring_soon",
        enabled=False,
        reason="recert reminders go to email only",
    )

    event = service.enqueue_expiring_soon_reminder(
        context, windows_days=[30], channels=["slack", "email"], as_of=AS_OF
    )

    assert event is not None
    assert event["status"] == "queued"
    assert event["delivery_count"] == 1
    pending = service.list_pending_deliveries(context)
    assert {delivery["channel"] for delivery in pending} == {"email"}


def test_requires_notifications_manage_permission(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "expiry-perm.db"))
    service = NotificationOutboxService(repo)
    # read_only role lacks notifications:manage.
    context = default_local_context(tenant_id="tenant-a", role="read_only")

    with pytest.raises(PermissionError):
        service.compute_expiring_soon(context, windows_days=[30], as_of=AS_OF)
