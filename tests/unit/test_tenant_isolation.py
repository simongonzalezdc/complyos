"""Cross-tenant PII isolation regression (WP9 / C1).

DSR export and right-to-erasure must be scoped by the real tenant_id column on
users/learning_records/enrollments. Previously tenancy was derived from a JSON
blob defaulting to "local-default" (which import never set) and the learning
record/enrollment queries had no tenant filter at all, so one tenant could
export or permanently delete another tenant's learning PII.
"""

from __future__ import annotations

from datetime import date

from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    Enrollment,
    EnrollmentStatus,
    LearningRecord,
    LearningRecordStatus,
    User,
)


def _seed_subject(repo: LocalRepository, *, tenant_id: str) -> None:
    repo.save_user(
        User(
            id="u-a",
            employee_id="E-a",
            email="a@example.com",
            first_name="A",
            last_name="Subject",
            department="Eng",
            region="US",
            hire_date=date(2024, 1, 1),
            custom_attributes={"tenant_id": tenant_id},
        )
    )
    repo.save_learning_record(
        LearningRecord(
            id="lr-a",
            user_id="u-a",
            course_id="c1",
            source_system="csv",
            status=LearningRecordStatus.COMPLETED,
        )
    )
    repo.save_enrollment(
        Enrollment(id="e-a", user_id="u-a", course_id="c1", status=EnrollmentStatus.COMPLETED)
    )


def test_export_and_delete_cannot_cross_tenant(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "tenants.db"))
    _seed_subject(repo, tenant_id="tenant-a")

    # A different tenant sees nothing for the same subject id.
    other = repo.get_subject_export("u-a", tenant_id="tenant-b")
    assert other["subject"] == {}
    assert other["learning_records"] == []
    assert other["enrollments"] == []

    # A different tenant's erasure is a no-op (cannot delete another's PII).
    deleted_other = repo.delete_subject_records("u-a", tenant_id="tenant-b")
    assert deleted_other == {"users": 0, "learning_records": 0, "enrollments": 0}

    # The owning tenant's data is intact after the cross-tenant attempts.
    own = repo.get_subject_export("u-a", tenant_id="tenant-a")
    assert own["subject"]["id"] == "u-a"
    assert len(own["learning_records"]) == 1
    assert len(own["enrollments"]) == 1

    # The owning tenant can erase its own subject.
    deleted_own = repo.delete_subject_records("u-a", tenant_id="tenant-a")
    assert deleted_own == {"users": 1, "learning_records": 1, "enrollments": 1}
    assert repo.get_subject_export("u-a", tenant_id="tenant-a")["subject"] == {}


def test_records_inherit_owning_users_tenant(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "inherit.db"))
    _seed_subject(repo, tenant_id="tenant-a")

    # learning record + enrollment, saved without an explicit tenant, inherited
    # tenant-a from their learner, so tenant-a (not local-default) can export.
    export = repo.get_subject_export("u-a", tenant_id="tenant-a")
    assert len(export["learning_records"]) == 1
    assert repo.get_subject_export("u-a", tenant_id="local-default")["learning_records"] == []
