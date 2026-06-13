"""Scheduled audit run helpers.

This module gives operators a deterministic one-shot runner that can be invoked
directly or by the generic systemd, cron, and Forgejo Action worker templates in
``deploy/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from complyos.core.dashboard import generate_dashboard
from complyos.models.domain import AuditReport


class AuditReporter(Protocol):
    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        """Generate an audit report."""


class SnapshotRepository(Protocol):
    def save_audit_snapshot(self, **kwargs: Any) -> str:
        """Persist an audit snapshot."""


class AuditSummaryNotifier(Protocol):
    async def send_audit_summary(self, report: AuditReport) -> dict[str, Any]:
        """Send an audit summary notification."""


@dataclass(frozen=True)
class ScheduledAuditJob:
    """Configuration for one recurring audit run."""

    name: str
    interval_hours: int
    department: str | None = None
    region: str | None = None
    dashboard_path: str | None = None
    last_run_at: datetime | None = None

    def is_due(self, now: datetime | None = None) -> bool:
        """Return True when the job should run at ``now``."""
        current = now or datetime.now(UTC)
        if self.last_run_at is None:
            return True
        return current - self.last_run_at >= timedelta(hours=self.interval_hours)


@dataclass(frozen=True)
class ScheduledAuditResult:
    """Result of one scheduled audit execution."""

    job_name: str
    generated_at: datetime
    scope: str
    gaps_found: int
    gaps_by_severity: dict[str, int]
    evidence_hash: str
    snapshot_id: str
    dashboard_path: str | None = None
    notification: dict[str, Any] | None = None


def load_scheduled_jobs(config_data: dict[str, Any]) -> list[ScheduledAuditJob]:
    """Load scheduled audit jobs from a config dictionary."""
    raw_jobs = config_data.get("schedule", {}).get("jobs", [])
    jobs: list[ScheduledAuditJob] = []
    for raw in raw_jobs:
        jobs.append(
            ScheduledAuditJob(
                name=str(raw["name"]),
                interval_hours=int(raw.get("interval_hours", 24)),
                department=raw.get("department"),
                region=raw.get("region"),
                dashboard_path=raw.get("dashboard_path"),
                last_run_at=raw.get("last_run_at"),
            )
        )
    return jobs


async def run_scheduled_audit_once(
    job: ScheduledAuditJob,
    *,
    auditor: AuditReporter,
    repository: SnapshotRepository,
    notifier: AuditSummaryNotifier | None = None,
) -> ScheduledAuditResult:
    """Run one scheduled audit job and persist its snapshot."""
    report = await auditor.generate_report(department=job.department, region=job.region)
    snapshot_id = repository.save_audit_snapshot(
        scope=report.scope,
        generated_at=report.generated_at,
        gaps_found=report.gaps_found,
        gaps=[gap.model_dump(mode="json") for gap in report.details],
        gaps_by_severity=report.gaps_by_severity,
        evidence_hash=report.evidence_hash,
    )

    dashboard_path = None
    if job.dashboard_path:
        path = Path(job.dashboard_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        dashboard_path = generate_dashboard(report, output_path=str(path))

    notification = None
    if notifier is not None:
        notification = await notifier.send_audit_summary(report)

    return ScheduledAuditResult(
        job_name=job.name,
        generated_at=report.generated_at,
        scope=report.scope,
        gaps_found=report.gaps_found,
        gaps_by_severity=report.gaps_by_severity,
        evidence_hash=report.evidence_hash,
        snapshot_id=snapshot_id,
        dashboard_path=dashboard_path,
        notification=notification,
    )
