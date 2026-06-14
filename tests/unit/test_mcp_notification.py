"""Tests for the MCP send_notification tool.

WP13b (P5/P9): send_notification is a mutating side effect (sends external
email) and is now gated at notifications:manage. The default proposal-only MCP
role (agent_service_account) lacks notifications:manage and is therefore DENIED
before any SMTP resolution or send; only an elevated COMPLYOS_MCP_ROLE may send.
This is the intentionally tightened least-privilege boundary; do not weaken it.
"""

from unittest.mock import AsyncMock, patch

import pytest

from complyos.api.mcp_server import send_notification
from complyos.services.context import AuthorizationError


@pytest.mark.asyncio
async def test_send_notification_denied_for_default_role(monkeypatch):
    """Default agent role is denied; no notifier is resolved and no email is sent."""
    monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
    mock_notifier = AsyncMock()
    with (
        patch(
            "complyos.api.mcp_server._get_notifier", return_value=mock_notifier
        ) as get_notifier,
        pytest.raises(AuthorizationError) as exc,
    ):
        await send_notification("to@example.com", "Subject", "Body")

    assert exc.value.permission == "notifications:manage"
    # Fail closed before any side effect: notifier never resolved, never sent.
    get_notifier.assert_not_called()
    mock_notifier.send_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_notification_not_configured_for_elevated_role(monkeypatch):
    """An elevated role passes the gate; an unconfigured SMTP yields a clean error."""
    monkeypatch.setenv("COMPLYOS_MCP_ROLE", "compliance_manager")
    with patch("complyos.api.mcp_server._get_notifier", return_value=None):
        result = await send_notification("to@example.com", "Subject", "Body")
    assert result["sent"] is False
    assert "not configured" in result["error"]


@pytest.mark.asyncio
async def test_send_notification_success_for_elevated_role(monkeypatch):
    """An elevated role that holds notifications:manage can send."""
    monkeypatch.setenv("COMPLYOS_MCP_ROLE", "compliance_manager")
    mock_notifier = AsyncMock()
    mock_notifier.send_email = AsyncMock(return_value={"sent": True})
    with patch("complyos.api.mcp_server._get_notifier", return_value=mock_notifier):
        result = await send_notification("to@example.com", "Subject", "Body")
    assert result["sent"] is True
    mock_notifier.send_email.assert_awaited_once_with(
        "to@example.com", "Subject", "Body"
    )
