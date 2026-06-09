"""Tests for CLI notify-test command."""

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_notify_test_missing_config():
    result = runner.invoke(app, ["notify-test", "user@example.com"])
    assert result.exit_code == 1
    assert "SMTP not configured" in result.output


def test_notify_test_success():
    with patch.dict(
        "os.environ",
        {
            "COMPLYOS_SMTP_HOST": "smtp.example.com",
            "COMPLYOS_SMTP_USERNAME": "u",
            "COMPLYOS_SMTP_PASSWORD": "p",
        },
        clear=False,
    ), patch(
        "complyos.notification.sender.aiosmtplib.send", new_callable=AsyncMock
    ):
        result = runner.invoke(app, ["notify-test", "user@example.com"])
    assert result.exit_code == 0
    assert "Test email sent" in result.output


def test_notify_test_failure():
    with patch.dict(
        "os.environ",
        {
            "COMPLYOS_SMTP_HOST": "smtp.example.com",
            "COMPLYOS_SMTP_USERNAME": "u",
            "COMPLYOS_SMTP_PASSWORD": "p",
        },
        clear=False,
    ), patch(
        "complyos.notification.sender.aiosmtplib.send",
        new_callable=AsyncMock,
        side_effect=Exception("SMTP down"),
    ):
        result = runner.invoke(app, ["notify-test", "user@example.com"])
    assert result.exit_code == 1
    assert "Failed to send email" in result.output
