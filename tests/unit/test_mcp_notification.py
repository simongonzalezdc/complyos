"""Tests for MCP send_notification tool."""

from unittest.mock import AsyncMock, patch

import pytest

from complyos.api.mcp_server import send_notification


@pytest.mark.asyncio
async def test_send_notification_not_configured():
    with patch("complyos.api.mcp_server._get_notifier", return_value=None):
        result = await send_notification("to@example.com", "Subject", "Body")
    assert result["sent"] is False
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_send_notification_success():
    mock_notifier = AsyncMock()
    mock_notifier.send_email = AsyncMock(return_value={"sent": True})
    with patch("complyos.api.mcp_server._get_notifier", return_value=mock_notifier):
        result = await send_notification("to@example.com", "Subject", "Body")
    assert result["sent"] is True
    mock_notifier.send_email.assert_awaited_once_with(
        "to@example.com", "Subject", "Body"
    )
