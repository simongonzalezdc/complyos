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

    async def sync(self, context: ActorContext) -> dict[str, int | str]:
        """Pull LMS data into the local cache (audit:run). Same flow as CLI ``sync``.

        This is intentionally mutating: it clears and re-populates the local
        cache. It is gated at audit:run because sync is the data-pull half of an
        audit, and tenant scope is carried on the context for the action log.
        """
        require_permission(context, PERM_AUDIT_RUN)
        healthy = await self.connector.authenticate()
        if not healthy:
            raise ValueError("connector authentication failed")
        users = await self.connector.get_users()
        courses = await self.connector.get_courses()
        enrollments = await self.connector.get_enrollments()
        learning_records = await self.connector.get_learning_records()
        self.repository.clear_all()
        self.repository.sync_users(users)
        self.repository.sync_courses(courses)
        self.repository.sync_enrollments(enrollments)
        self.repository.sync_learning_records(learning_records)
        return {
            "connector": self.connector.name,
            "users": len(users),
            "courses": len(courses),
            "enrollments": len(enrollments),
            "learning_records": len(learning_records),
        }
