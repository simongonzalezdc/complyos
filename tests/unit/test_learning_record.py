"""Tests for cross-LMS LearningRecord domain model."""

from __future__ import annotations

from datetime import date, datetime

from complyos.models.domain import (
    Enrollment,
    EnrollmentStatus,
    LearningRecord,
    LearningRecordStatus,
)


def test_learning_record_defaults_to_assigned():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="canvas",
        source_record_id="canvas-123",
    )

    assert record.status == LearningRecordStatus.ASSIGNED
    assert record.completion_percentage == 0.0
    assert record.is_compliant is False


def test_completed_learning_record_is_compliant():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="cornerstone",
        status=LearningRecordStatus.COMPLETED,
        completed_date=datetime(2026, 1, 15, 9, 30),
        completion_percentage=100,
        raw_source_hash="abc123",
    )

    assert record.is_compliant is True
    assert record.raw_source_hash == "abc123"


def test_exempt_learning_record_is_compliant():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="workday",
        status=LearningRecordStatus.EXEMPT,
        exempt=True,
    )

    assert record.is_compliant is True


def test_learning_record_from_enrollment_preserves_existing_fields():
    enrollment = Enrollment(
        id="e1",
        user_id="u1",
        course_id="c1",
        status=EnrollmentStatus.IN_PROGRESS,
        assigned_date=datetime(2026, 1, 1, 8, 0),
        due_date=date(2026, 2, 1),
        completion_percentage=50,
        score=87.5,
    )

    record = LearningRecord.from_enrollment(enrollment, source_system="legacy")

    assert record.id == "e1"
    assert record.user_id == "u1"
    assert record.course_id == "c1"
    assert record.source_system == "legacy"
    assert record.status == LearningRecordStatus.IN_PROGRESS
    assert record.due_date == date(2026, 2, 1)
    assert record.score == 87.5


def test_learning_record_to_enrollment_is_backward_compatible():
    record = LearningRecord(
        id="lr1",
        user_id="u1",
        course_id="c1",
        source_system="docebo",
        status=LearningRecordStatus.EXPIRED,
        assigned_date=datetime(2026, 1, 1, 8, 0),
        due_date=date(2026, 2, 1),
        completed_date=datetime(2026, 1, 20, 8, 0),
        completion_percentage=100,
        score=91.0,
        expires_at=date(2027, 1, 20),
    )

    enrollment = record.to_enrollment()

    assert enrollment.id == "lr1"
    assert enrollment.user_id == "u1"
    assert enrollment.course_id == "c1"
    assert enrollment.status == EnrollmentStatus.OVERDUE
    assert enrollment.completed_date == datetime(2026, 1, 20, 8, 0)
    assert enrollment.completion_percentage == 100
    assert enrollment.score == 91.0
