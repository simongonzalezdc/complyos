"""Tests for notification email templates."""

from datetime import date

from complyos.models.domain import ComplianceGap, Course, EmploymentStatus, User
from complyos.notification.templates import (
    render_manager_notification,
    render_reminder,
)


def test_render_reminder():
    user = User(
        id="u1",
        employee_id="E001",
        email="alice@example.com",
        first_name="Alice",
        last_name="Smith",
        department="Engineering",
        region="US",
        hire_date=date(2020, 1, 15),
        employment_status=EmploymentStatus.ACTIVE,
    )
    course = Course(id="c1", code="SAFE-101", title="Safety Basics")
    gap = ComplianceGap(user=user, missing_courses=[course], days_overdue=5)

    subject, body = render_reminder(user, course, gap)
    assert "Safety Basics" in subject
    assert "Hi Alice," in body
    assert "5 day(s) overdue" in body


def test_render_reminder_without_gap():
    user = User(
        id="u2",
        employee_id="E002",
        email="bob@example.com",
        first_name="Bob",
        last_name="Jones",
        department="HR",
        region="MX",
        hire_date=date(2021, 3, 10),
        employment_status=EmploymentStatus.ACTIVE,
    )
    course = Course(id="c2", code="ETH-101", title="Ethics Training")

    subject, body = render_reminder(user, course)
    assert "Ethics Training" in subject
    assert "Hi Bob," in body
    assert "overdue" not in body


def test_render_manager_notification():
    user = User(
        id="u3",
        employee_id="E003",
        email="charlie@example.com",
        first_name="Charlie",
        last_name="Brown",
        department="Finance",
        region="US",
        hire_date=date(2019, 6, 1),
        employment_status=EmploymentStatus.ACTIVE,
        manager_id="m1",
    )
    course = Course(id="c3", code="AML-101", title="Anti-Money Laundering")
    gap = ComplianceGap(user=user, missing_courses=[course], days_overdue=12)

    subject, body = render_manager_notification(user, course, gap)
    assert "Charlie Brown" in subject
    assert "Anti-Money Laundering" in body
    assert "12" in body
    assert "Manager Notification" in body
