"""Service wrapper for evidence export and ledger reads.

The report/evidence surfaces (CLI export, MCP export_audit_report_html, API
/evidence) used to call core report-export and repository code directly while
enforcing permissions at the surface. This service makes the service layer the
single authorization choke-point: export_report requires evidence:export and
list_ledger requires evidence:read. Return shapes are unchanged.
"""

from __future__ import annotations

import csv
from datetime import date
from html import escape
from io import StringIO
from typing import Any

from pydantic import BaseModel

from complyos.connectors.base import LMSConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.report_exporter import export_html, render_html
from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_EVIDENCE_EXPORT,
    PERM_EVIDENCE_READ,
    ActorContext,
    require_permission,
)

FORMULA_PREFIXES = ("=", "+", "-", "@")


class TrainingRecordStatusRow(BaseModel):
    """Rendered training-record status for read and packet surfaces."""

    learner: str
    training: str
    completed_date: str
    renewal_date: str
    status: str
    expired: bool


class EvidenceService:
    """Authorization-gated audit-report export and evidence-ledger reads."""

    def __init__(
        self,
        connector: LMSConnector,
        repository: LocalRepository | None = None,
    ) -> None:
        self.connector = connector
        self.repository = repository or LocalRepository()

    async def export_report(
        self,
        context: ActorContext,
        *,
        output_path: str = "report.html",
        department: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Generate an audit report and export it to a styled HTML file."""
        require_permission(context, PERM_EVIDENCE_EXPORT)
        report = await ComplianceAuditor(self.connector).generate_report(
            department=department, region=region
        )
        path = export_html(report, output_path)
        return {
            "output_path": path,
            "gaps_found": report.gaps_found,
            "total_users": report.total_users_audited,
            "evidence_hash": report.evidence_hash,
        }

    async def render_report(
        self,
        context: ActorContext,
        *,
        department: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """Render an audit report and return its content in memory (no disk write).

        Same evidence:export choke-point as ``export_report``, but returns the
        rendered HTML body plus the evidence hash instead of writing a file. This
        lets a remote surface (the API) export a report without ever writing PII
        to arbitrary server disk from a remote call.
        """
        require_permission(context, PERM_EVIDENCE_EXPORT)
        report = await ComplianceAuditor(self.connector).generate_report(
            department=department, region=region
        )
        return {
            "format": "html",
            "content": render_html(report),
            "gaps_found": report.gaps_found,
            "total_users": report.total_users_audited,
            "evidence_hash": report.evidence_hash,
        }

    def list_ledger(
        self,
        context: ActorContext,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tenant-scoped evidence ledger entries."""
        require_permission(context, PERM_EVIDENCE_READ)
        return self.repository.list_evidence_ledger(tenant_id=context.tenant_id, limit=limit)

    def list_training_record_status(
        self,
        context: ActorContext,
        *,
        as_of: date | None = None,
    ) -> list[TrainingRecordStatusRow]:
        """List tenant-scoped normalized training records for operator review."""
        require_permission(context, PERM_EVIDENCE_READ)
        return self._training_record_status_rows(context.tenant_id, as_of=as_of)

    def render_training_record_packet_csv(
        self,
        context: ActorContext,
        *,
        as_of: date | None = None,
    ) -> str:
        """Render a client-facing status packet as CSV."""
        require_permission(context, PERM_EVIDENCE_EXPORT)
        rows = self._training_record_status_rows(context.tenant_id, as_of=as_of)
        output = StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["learner", "training", "completed_date", "renewal_date", "status"])
        for row in rows:
            writer.writerow(
                [
                    _neutralize_cell(row.learner),
                    _neutralize_cell(row.training),
                    row.completed_date,
                    row.renewal_date,
                    row.status,
                ]
            )
        return output.getvalue()

    def render_training_record_packet_html(
        self,
        context: ActorContext,
        *,
        as_of: date | None = None,
    ) -> str:
        """Render a minimal client-facing status packet as HTML."""
        require_permission(context, PERM_EVIDENCE_EXPORT)
        rows = self._training_record_status_rows(context.tenant_id, as_of=as_of)
        body = "\n".join(
            "<tr>"
            f"<td>{escape(row.learner)}</td>"
            f"<td>{escape(row.training)}</td>"
            f"<td>{escape(row.completed_date)}</td>"
            f"<td>{escape(row.renewal_date)}</td>"
            f"<td>{escape(row.status)}</td>"
            "</tr>"
            for row in rows
        )
        if not body:
            body = "<tr><td colspan='5'>No normalized training records.</td></tr>"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Client-facing status packet</title>
</head>
<body>
  <h1>client-facing status packet</h1>
  <table>
    <thead>
      <tr>
        <th scope="col">Learner</th>
        <th scope="col">Training</th>
        <th scope="col">Completed date</th>
        <th scope="col">Renewal date</th>
        <th scope="col">Status</th>
      </tr>
    </thead>
    <tbody>
      {body}
    </tbody>
  </table>
</body>
</html>"""

    def _training_record_status_rows(
        self,
        tenant_id: str,
        *,
        as_of: date | None,
    ) -> list[TrainingRecordStatusRow]:
        records = self.repository.list_learning_records(tenant_id=tenant_id)
        rows: list[TrainingRecordStatusRow] = []
        for record in records:
            user = self.repository.get_user(record.user_id)
            course = self.repository.get_course(record.course_id)
            learner = user.full_name.strip() if user and user.full_name.strip() else record.user_id
            training = course.title if course else record.course_id
            expired = record.is_expired(as_of=as_of)
            status = "overdue" if expired else record.status.value
            completed = record.completed_date.date().isoformat() if record.completed_date else ""
            renewal = record.expires_at.isoformat() if record.expires_at else ""
            rows.append(
                TrainingRecordStatusRow(
                    learner=learner,
                    training=training,
                    completed_date=completed,
                    renewal_date=renewal,
                    status=status,
                    expired=expired,
                )
            )
        return sorted(rows, key=lambda row: (row.learner.lower(), row.training.lower()))


def _neutralize_cell(value: str) -> str:
    return f"'{value}" if value.startswith(FORMULA_PREFIXES) else value
