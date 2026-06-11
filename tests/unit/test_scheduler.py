"""Tests for operator scheduled audit runs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from complyos.core.scheduler import (
    ScheduledAuditJob,
    load_scheduled_jobs,
    run_scheduled_audit_once,
)
from complyos.models.domain import AuditReport


class FakeAuditor:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        self.calls.append({"department": department, "region": region})
        return AuditReport(
            generated_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
            scope="department=Security, region=US",
            total_users_audited=4,
            gaps_found=2,
            gaps_by_severity={"low": 0, "medium": 1, "high": 1, "critical": 0},
            gaps_by_department={"Security": 2},
            top_missing_courses=[("Security Annual", 2)],
            evidence_hash="abc123",
            details=[],
        )


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    def save_audit_snapshot(self, **kwargs: Any) -> str:
        self.saved.append(kwargs)
        return "snapshot-1"


class FakeNotifier:
    def __init__(self) -> None:
        self.payloads: list[AuditReport] = []

    async def send_audit_summary(self, report: AuditReport) -> dict[str, Any]:
        self.payloads.append(report)
        return {"sent": True, "channels": ["slack"]}


def test_scheduled_audit_job_is_due_when_interval_elapsed() -> None:
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    job = ScheduledAuditJob(
        name="daily-security",
        interval_hours=24,
        department="Security",
        region="US",
        last_run_at=now - timedelta(hours=25),
    )

    assert job.is_due(now) is True


def test_scheduled_audit_job_is_not_due_before_interval() -> None:
    now = datetime(2026, 6, 11, 12, 0, tzinfo=UTC)
    job = ScheduledAuditJob(
        name="daily-security",
        interval_hours=24,
        last_run_at=now - timedelta(hours=2),
    )

    assert job.is_due(now) is False


def test_load_scheduled_jobs_from_config_data() -> None:
    jobs = load_scheduled_jobs(
        {
            "schedule": {
                "jobs": [
                    {
                        "name": "weekly-campus",
                        "interval_hours": 168,
                        "department": "Clinical Education",
                        "region": "US",
                        "dashboard_path": "reports/campus.html",
                    }
                ]
            }
        }
    )

    assert jobs == [
        ScheduledAuditJob(
            name="weekly-campus",
            interval_hours=168,
            department="Clinical Education",
            region="US",
            dashboard_path="reports/campus.html",
        )
    ]


@pytest.mark.asyncio
async def test_run_scheduled_audit_once_saves_snapshot_and_notifies() -> None:
    auditor = FakeAuditor()
    repository = FakeRepository()
    notifier = FakeNotifier()
    job = ScheduledAuditJob(
        name="daily-security",
        interval_hours=24,
        department="Security",
        region="US",
    )

    result = await run_scheduled_audit_once(
        job,
        auditor=auditor,
        repository=repository,
        notifier=notifier,
    )

    assert result.job_name == "daily-security"
    assert result.snapshot_id == "snapshot-1"
    assert result.gaps_found == 2
    assert result.notification == {"sent": True, "channels": ["slack"]}
    assert auditor.calls == [{"department": "Security", "region": "US"}]
    assert repository.saved[0]["scope"] == "department=Security, region=US"
    assert notifier.payloads[0].evidence_hash == "abc123"
