"""Service wrapper for the audit/report/status/digest flow.

Routes, MCP tools, and CLI commands used to call ComplianceAuditor/DigestEngine
directly and enforce permissions only at the surface. This service makes the
service layer the single authorization choke-point: every method accepts an
ActorContext and calls require_permission before touching the engines. Return
shapes match what the surfaces produced before the wrapper existed.
"""

from __future__ import annotations

from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.digest import ComplianceDigest, DigestEngine
from complyos.core.repository import LocalRepository
from complyos.models.domain import AuditReport, ComplianceGap, EvidenceLedgerEntry
from complyos.services.context import (
    PERM_AUDIT_READ,
    PERM_AUDIT_RUN,
    ActorContext,
    require_permission,
)


class AuditService:
    """Authorization-gated audit, report, status, and digest operations."""

    def __init__(
        self,
        connector: LMSConnector,
        repository: LocalRepository | None = None,
    ) -> None:
        self.connector = connector
        self.repository = repository or LocalRepository()

    async def run_audit(
        self,
        context: ActorContext,
        *,
        department: str | None = None,
        region: str | None = None,
    ) -> tuple[list[ComplianceGap], EvidenceLedgerEntry]:
        """Audit compliance gaps. Returns the gaps and evidence ledger entry."""
        require_permission(context, PERM_AUDIT_RUN)
        return await ComplianceAuditor(self.connector).audit_gaps(
            department=department, region=region
        )

    async def generate_report(
        self,
        context: ActorContext,
        *,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        """Generate a structured audit report (runs an audit under the hood)."""
        require_permission(context, PERM_AUDIT_RUN)
        return await ComplianceAuditor(self.connector).generate_report(
            department=department, region=region
        )

    async def get_status(self, context: ActorContext, *, user_id: str) -> dict[str, Any]:
        """Get the complete compliance status for a single user."""
        require_permission(context, PERM_AUDIT_READ)
        return await ComplianceAuditor(self.connector).get_user_status(user_id)

    async def get_digest(
        self,
        context: ActorContext,
        *,
        department: str | None = None,
        region: str | None = None,
    ) -> ComplianceDigest:
        """Generate a what-changed digest against the previous audit snapshot."""
        require_permission(context, PERM_AUDIT_READ)
        engine = DigestEngine(ComplianceAuditor(self.connector), self.repository)
        return await engine.generate(department=department, region=region)
