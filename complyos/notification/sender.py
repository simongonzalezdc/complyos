"""Async email notification sender using SMTP."""

from __future__ import annotations

import os
from email.message import EmailMessage
from typing import Any

import aiosmtplib

from complyos.models.domain import ComplianceGap, Course, User
from complyos.notification.templates import render_manager_notification, render_reminder


class NotificationSender:
    """Send compliance notifications via SMTP."""

    def __init__(
        self,
        host: str | None = None,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        from_address: str = "complyos@example.com",
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.from_address = from_address

    @property
    def enabled(self) -> bool:
        """Return True if SMTP is configured and ready."""
        return bool(self.host and self.username and self.password)

    async def send_email(
        self,
        to_address: str,
        subject: str,
        body: str,
    ) -> dict[str, Any]:
        """Send a plain-text email.

        Returns:
            Dict with 'sent' boolean and optional 'error' string.
        """
        if not self.enabled:
            return {"sent": False, "error": "SMTP not configured"}

        message = EmailMessage()
        message["From"] = self.from_address
        message["To"] = to_address
        message["Subject"] = subject
        message.set_content(body)

        try:
            await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )
            return {"sent": True}
        except Exception as exc:
            return {"sent": False, "error": str(exc)}

    async def send_reminder(
        self,
        user: User,
        course: Course,
        gap: ComplianceGap | None = None,
    ) -> dict[str, Any]:
        """Send a reminder email to a user about a missing course."""
        subject, body = render_reminder(user, course, gap)
        return await self.send_email(user.email, subject, body)

    async def send_manager_notification(
        self,
        manager_email: str,
        user: User,
        course: Course,
        gap: ComplianceGap | None = None,
    ) -> dict[str, Any]:
        """Notify a manager about a critical compliance gap."""
        subject, body = render_manager_notification(user, course, gap)
        return await self.send_email(manager_email, subject, body)


def build_notifier_from_env() -> NotificationSender | None:
    """Build a NotificationSender from COMPLYOS_SMTP_* env vars, or None.

    Single source of truth shared by the CLI and MCP surfaces so SMTP
    credential resolution (env-var names, default port, required fields) cannot
    drift between them.
    """
    host = os.getenv("COMPLYOS_SMTP_HOST")
    username = os.getenv("COMPLYOS_SMTP_USERNAME")
    password = os.getenv("COMPLYOS_SMTP_PASSWORD")
    if not (host and username and password):
        return None
    return NotificationSender(
        host=host,
        port=int(os.getenv("COMPLYOS_SMTP_PORT", "587")),
        username=username,
        password=password,
        from_address=os.getenv("COMPLYOS_SMTP_FROM", "complyos@example.com"),
    )
