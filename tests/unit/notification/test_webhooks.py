"""Tests for Slack and Teams webhook notifications."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from complyos.models.domain import AuditReport
from complyos.notification.webhooks import WebhookNotifier


def _report() -> AuditReport:
    return AuditReport(
        generated_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
        scope="all",
        total_users_audited=8,
        gaps_found=3,
        gaps_by_severity={"low": 0, "medium": 2, "high": 1, "critical": 0},
        gaps_by_department={"Operations": 2, "Security": 1},
        top_missing_courses=[("Security Annual", 3)],
        evidence_hash="feedface",
        details=[],
    )


@pytest.mark.asyncio
@respx.mock
async def test_send_audit_summary_posts_slack_text_payload() -> None:
    route = respx.post("https://hooks.slack.test/services/T/B/secret").mock(
        return_value=Response(200, text="ok")
    )
    notifier = WebhookNotifier(slack_webhook_url="https://hooks.slack.test/services/T/B/secret")

    result = await notifier.send_audit_summary(_report())

    assert result == {"sent": True, "channels": ["slack"], "errors": {}}
    payload = route.calls[0].request.read()
    assert b'"text"' in payload
    assert b"ComplyOS audit: 3 gaps across 8 audited users" in payload
    assert b"feedface" in payload


@pytest.mark.asyncio
@respx.mock
async def test_send_audit_summary_posts_teams_workflow_payload() -> None:
    route = respx.post("https://teams.test/workflows/secret").mock(return_value=Response(202))
    notifier = WebhookNotifier(teams_webhook_url="https://teams.test/workflows/secret")

    result = await notifier.send_audit_summary(_report())

    assert result == {"sent": True, "channels": ["teams"], "errors": {}}
    payload = route.calls[0].request.read()
    assert b'"title":"ComplyOS audit summary"' in payload
    assert b'"gaps_found":3' in payload
    assert b'"evidence_hash":"feedface"' in payload


@pytest.mark.asyncio
async def test_send_audit_summary_reports_not_configured() -> None:
    notifier = WebhookNotifier()

    result = await notifier.send_audit_summary(_report())

    assert result == {
        "sent": False,
        "channels": [],
        "errors": {"configuration": "No Slack or Teams webhook URL configured"},
    }
