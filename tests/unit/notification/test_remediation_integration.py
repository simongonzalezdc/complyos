"""Tests for remediation engine integration with notifications."""

from datetime import date
from unittest.mock import AsyncMock

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.remediation import RemediationEngine
from complyos.models.domain import ComplianceGap, Course, EmploymentStatus, User
from complyos.notification.sender import NotificationSender


def make_user(**kwargs):
    defaults = {
        "id": "u1",
        "employee_id": "E001",
        "email": "alice@example.com",
        "first_name": "Alice",
        "last_name": "Smith",
        "department": "Engineering",
        "region": "US",
        "hire_date": date(2020, 1, 15),
        "employment_status": EmploymentStatus.ACTIVE,
    }
    defaults.update(kwargs)
    return User(**defaults)


def make_course():
    return Course(id="c1", code="SAFE-101", title="Safety Basics")


def make_gap(user, course, severity="critical", days_overdue=None):
    return ComplianceGap(
        user=user,
        missing_courses=[course],
        severity=severity,
        days_overdue=days_overdue,
    )


@pytest.mark.asyncio
async def test_notify_manager_with_email():
    connector = MockConnector()
    notifier = NotificationSender(
        host="smtp.example.com",
        port=587,
        username="u",
        password="p",
    )
    notifier.send_manager_notification = AsyncMock(return_value={"sent": True})

    engine = RemediationEngine(connector, notifier=notifier)
    user = make_user(manager_id="m1")
    course = make_course()
    gap = make_gap(user, course)

    actions = await engine.remediate_gaps(
        [gap], auto_remind=False, notify_manager=True
    )

    manager_actions = [a for a in actions if a.action_type == "notify_manager"]
    assert len(manager_actions) == 1
    assert manager_actions[0].status == "sent"
    notifier.send_manager_notification.assert_awaited_once()


@pytest.mark.asyncio
async def test_notify_manager_without_email():
    connector = MockConnector()
    engine = RemediationEngine(connector, notifier=None)
    user = make_user(manager_id="m1")
    course = make_course()
    gap = make_gap(user, course)

    actions = await engine.remediate_gaps(
        [gap], auto_remind=False, notify_manager=True
    )

    manager_actions = [a for a in actions if a.action_type == "notify_manager"]
    assert len(manager_actions) == 1
    assert manager_actions[0].status == "sent"


@pytest.mark.asyncio
async def test_reminder_triggers_email():
    connector = MockConnector()
    notifier = NotificationSender(
        host="smtp.example.com",
        port=587,
        username="u",
        password="p",
    )
    notifier.send_reminder = AsyncMock(return_value={"sent": True})

    engine = RemediationEngine(connector, notifier=notifier)
    user = make_user()
    course = make_course()
    gap = make_gap(user, course, severity="high")

    actions = await engine.remediate_gaps(
        [gap], auto_remind=True, notify_manager=False
    )

    reminder_actions = [a for a in actions if a.action_type == "reminder"]
    assert len(reminder_actions) == 1
    notifier.send_reminder.assert_awaited_once()
