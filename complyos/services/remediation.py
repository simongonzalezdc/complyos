"""Service wrapper for the remediation propose/execute flow.

Routes, MCP tools, and the CLI used to audit gaps and call RemediationEngine
directly while enforcing permissions only at the surface. This service makes
the service layer the single authorization choke-point:

- propose (dry-run, remediation:propose) computes the actions that *would* be
  taken without sending reminders, emails, or webhooks.
- execute (remediation:execute) applies the mutating remediation, identical to
  the behavior the surfaces had before.

Both methods return the (gaps, actions, ledger) triple so callers can shape the
response exactly as before via complyos.core.audit_views.shape_remediation.
"""

from __future__ import annotations

from typing import Any

from complyos.connectors.base import LMSConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.remediation import RemediationEngine
from complyos.models.domain import (
    ComplianceGap,
    Course,
    Enrollment,
    EvidenceLedgerEntry,
    RemediationAction,
    User,
)
from complyos.notification.sender import NotificationSender
from complyos.services.context import (
    PERM_REMEDIATION_EXECUTE,
    PERM_REMEDIATION_PROPOSE,
    ActorContext,
    require_permission,
)


class _DryRunConnector(LMSConnector):
    """Read-through connector that suppresses the reminder side effect.

    Reads delegate to the real connector so the proposed actions reflect live
    data, but trigger_reminder never reaches the LMS — a dry-run proposal must
    not send anything.
    """

    name = "dry-run"

    def __init__(self, connector: LMSConnector) -> None:
        self._connector = connector

    async def authenticate(self) -> bool:
        return await self._connector.authenticate()

    async def get_users(self, filters: dict[str, Any] | None = None) -> list[User]:
        return await self._connector.get_users(filters)

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list[Course]:
        return await self._connector.get_courses(filters)

    async def get_enrollments(
        self, user_ids: list[str] | None = None, course_ids: list[str] | None = None
    ) -> list[Enrollment]:
        return await self._connector.get_enrollments(user_ids=user_ids, course_ids=course_ids)

    async def trigger_reminder(self, user_id: str, course_id: str) -> bool:
        return True


class RemediationService:
    """Authorization-gated remediation proposal and execution."""

    def __init__(
        self,
        connector: LMSConnector,
        notifier: NotificationSender | None = None,
    ) -> None:
        self.connector = connector
        self.notifier = notifier

    async def propose(
        self,
        context: ActorContext,
        *,
        department: str | None = None,
        region: str | None = None,
        auto_remind: bool = True,
        auto_enroll: bool = False,
        notify_manager: bool = False,
    ) -> tuple[list[ComplianceGap], list[RemediationAction], EvidenceLedgerEntry]:
        """Dry-run: compute the remediation actions without any side effects."""
        require_permission(context, PERM_REMEDIATION_PROPOSE)
        gaps, ledger = await ComplianceAuditor(self.connector).audit_gaps(
            department=department, region=region
        )
        engine = RemediationEngine(_DryRunConnector(self.connector), notifier=None)
        actions = await engine.remediate_gaps(
            gaps,
            auto_remind=auto_remind,
            auto_enroll=auto_enroll,
            notify_manager=notify_manager,
        )
        return gaps, actions, ledger

    async def execute(
        self,
        context: ActorContext,
        *,
        department: str | None = None,
        region: str | None = None,
        auto_remind: bool = True,
        auto_enroll: bool = False,
        notify_manager: bool = False,
    ) -> tuple[list[ComplianceGap], list[RemediationAction], EvidenceLedgerEntry]:
        """Audit and apply mutating remediation actions to the found gaps."""
        require_permission(context, PERM_REMEDIATION_EXECUTE)
        gaps, ledger = await ComplianceAuditor(self.connector).audit_gaps(
            department=department, region=region
        )
        engine = RemediationEngine(self.connector, notifier=self.notifier)
        actions = await engine.remediate_gaps(
            gaps,
            auto_remind=auto_remind,
            auto_enroll=auto_enroll,
            notify_manager=notify_manager,
        )
        return gaps, actions, ledger
