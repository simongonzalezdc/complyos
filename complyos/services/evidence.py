"""Service wrapper for evidence export and ledger reads.

The report/evidence surfaces (CLI export, MCP export_audit_report_html, API
/evidence) used to call core report-export and repository code directly while
enforcing permissions at the surface. This service makes the service layer the
single authorization choke-point: export_report requires evidence:export and
list_ledger requires evidence:read. Return shapes are unchanged.
"""

from __future__ import annotations

from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.report_exporter import export_html
from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_EVIDENCE_EXPORT,
    PERM_EVIDENCE_READ,
    ActorContext,
    require_permission,
)


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

    def list_ledger(
        self,
        context: ActorContext,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List tenant-scoped evidence ledger entries."""
        require_permission(context, PERM_EVIDENCE_READ)
        return self.repository.list_evidence_ledger(tenant_id=context.tenant_id, limit=limit)
