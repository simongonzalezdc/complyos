"""Tests for NotificationSender."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from complyos.models.domain import Course, EmploymentStatus, User
from complyos.notification.sender import NotificationSender


@pytest.fixture
def sender():
    return NotificationSender(
        host="smtp.example.com",
        port=587,
        username="user",
        password="pass",
        from_address="complyos@example.com",
    )


@pytest.fixture
def user():
    return User(
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


@pytest.fixture
def course():
    return Course(id="c1", code="SAFE-101", title="Safety Basics")


def test_enabled_when_configured(sender):
    assert sender.enabled is True


def test_disabled_when_incomplete():
    incomplete = NotificationSender(host="smtp.example.com")
    assert incomplete.enabled is False


@pytest.mark.asyncio
async def test_send_email_success(sender):
    with patch("complyos.notification.sender.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        result = await sender.send_email("to@example.com", "Subject", "Body")
        assert result["sent"] is True
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_email_failure(sender):
    with patch(
        "complyos.notification.sender.aiosmtplib.send",
        new_callable=AsyncMock,
        side_effect=Exception("SMTP error"),
    ):
        result = await sender.send_email("to@example.com", "Subject", "Body")
        assert result["sent"] is False
        assert "SMTP error" in result["error"]


@pytest.mark.asyncio
async def test_send_email_not_configured():
    sender = NotificationSender()
    result = await sender.send_email("to@example.com", "Subject", "Body")
    assert result["sent"] is False
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_send_reminder(sender, user, course):
    with patch("complyos.notification.sender.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        result = await sender.send_reminder(user, course)
        assert result["sent"] is True
        mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_manager_notification(sender, user, course):
    with patch("complyos.notification.sender.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        result = await sender.send_manager_notification("boss@example.com", user, course)
        assert result["sent"] is True
        mock_send.assert_awaited_once()
