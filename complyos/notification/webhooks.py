"""Slack and Teams webhook notifications for audit summaries."""

from __future__ import annotations

from typing import Any

import httpx

from complyos.models.domain import AuditReport


class WebhookNotifier:
    """Send audit summaries to Slack incoming webhooks and Teams Workflows."""

    def __init__(
        self,
        *,
        slack_webhook_url: str | None = None,
        teams_webhook_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.slack_webhook_url = slack_webhook_url
        self.teams_webhook_url = teams_webhook_url
        self.timeout = timeout

    @property
    def enabled_channels(self) -> list[str]:
        """Return configured webhook channels."""
        channels: list[str] = []
        if self.slack_webhook_url:
            channels.append("slack")
        if self.teams_webhook_url:
            channels.append("teams")
        return channels

    async def send_audit_summary(self, report: AuditReport) -> dict[str, Any]:
        """Send a concise audit summary to every configured webhook."""
        if not self.enabled_channels:
            return {
                "sent": False,
                "channels": [],
                "errors": {"configuration": "No Slack or Teams webhook URL configured"},
            }

        sent_channels: list[str] = []
        errors: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            if self.slack_webhook_url:
                try:
                    response = await client.post(
                        self.slack_webhook_url,
                        json=_slack_payload(report),
                    )
                    response.raise_for_status()
                    sent_channels.append("slack")
                except Exception as exc:  # pragma: no cover - exercised by callers
                    errors["slack"] = str(exc)

            if self.teams_webhook_url:
                try:
                    response = await client.post(
                        self.teams_webhook_url,
                        json=_teams_payload(report),
                    )
                    response.raise_for_status()
                    sent_channels.append("teams")
                except Exception as exc:  # pragma: no cover - exercised by callers
                    errors["teams"] = str(exc)

        return {
            "sent": bool(sent_channels) and not errors,
            "channels": sent_channels,
            "errors": errors,
        }


def _summary_text(report: AuditReport) -> str:
    return (
        f"ComplyOS audit: {report.gaps_found} gaps across "
        f"{report.total_users_audited} audited users. "
        f"Scope: {report.scope}. Evidence: {report.evidence_hash}."
    )


def _slack_payload(report: AuditReport) -> dict[str, Any]:
    text = _summary_text(report)
    return {
        "text": text,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*ComplyOS audit summary*\\n{text}"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Gaps*\\n{report.gaps_found}"},
                    {"type": "mrkdwn", "text": f"*Scope*\\n{report.scope}"},
                    {"type": "mrkdwn", "text": f"*Evidence*\\n{report.evidence_hash}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Generated*\\n{report.generated_at.isoformat()}",
                    },
                ],
            },
        ],
    }


def _teams_payload(report: AuditReport) -> dict[str, Any]:
    return {
        "title": "ComplyOS audit summary",
        "text": _summary_text(report),
        "scope": report.scope,
        "gaps_found": report.gaps_found,
        "total_users_audited": report.total_users_audited,
        "gaps_by_severity": report.gaps_by_severity,
        "evidence_hash": report.evidence_hash,
        "generated_at": report.generated_at.isoformat(),
    }
