"""Security evidence-room packet generation.

This module maps current repository evidence to security control readiness.
It is intentionally readiness-only: it does not claim SOC 2 certification,
audit completion, or legal status.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field

from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_SECURITY_EVIDENCE_READ,
    ActorContext,
    require_permission,
)


class SecurityControlEvidence(BaseModel):
    control_id: str
    control_name: str
    status: str
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_tasks: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class SecurityEvidencePacket(BaseModel):
    tenant_id: str
    period: str
    posture: str = "readiness_only"
    generated_at: datetime
    summary: dict[str, int] = Field(default_factory=dict)
    controls: list[SecurityControlEvidence]
    actor_context: dict[str, str] = Field(default_factory=dict)


class SecurityEvidenceService:
    """Assemble an auditor-review packet from existing local evidence."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def collect_packet(
        self,
        context: ActorContext,
        *,
        period: str,
    ) -> SecurityEvidencePacket:
        require_permission(context, PERM_SECURITY_EVIDENCE_READ)
        action_logs = self.repository.list_action_logs(tenant_id=context.tenant_id)
        evidence_entries = self.repository.list_evidence_ledger(tenant_id=context.tenant_id)
        generated_at = datetime.now(UTC)
        controls = self._controls(
            action_log_count=len(action_logs),
            evidence_entry_count=len(evidence_entries),
        )
        summary = {
            "controls_total": len(controls),
            "controls_partial": sum(1 for control in controls if control.status == "partial"),
            "controls_need_evidence": sum(
                1 for control in controls if control.status == "needs_evidence"
            ),
            "action_logs": len(action_logs),
            "evidence_entries": len(evidence_entries),
        }
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="security.evidence.packet",
            object_type="security_evidence_packet",
            object_id=period,
            result="readiness_only",
            request_id=context.request_id,
            metadata=summary,
        )
        return SecurityEvidencePacket(
            tenant_id=context.tenant_id,
            period=period,
            generated_at=generated_at,
            summary=summary,
            controls=controls,
            actor_context=context.public_dict(),
        )

    @staticmethod
    def _controls(
        *,
        action_log_count: int,
        evidence_entry_count: int,
    ) -> list[SecurityControlEvidence]:
        return [
            SecurityControlEvidence(
                control_id="CC6.1",
                control_name="Logical access controls",
                status="partial",
                evidence_refs=[
                    "complyos/services/context.py",
                    "tests/unit/test_authz.py",
                    "complyos/web/api_v1.py",
                ],
                evidence_tasks=[
                    "docs/access-review-procedure.md",
                ],
                gaps=[
                    "production SSO/MFA evidence",
                    "quarterly access review evidence",
                    "joiner/mover/leaver tickets",
                ],
                next_actions=[
                    "connect production identity provider",
                    "export access-review packet each quarter",
                ],
            ),
            SecurityControlEvidence(
                control_id="CC7.2",
                control_name="System monitoring and audit logging",
                status="partial" if action_log_count else "needs_evidence",
                evidence_refs=[
                    "audit_action_logs table",
                    "complyos/core/repository.py",
                    f"action_log_count:{action_log_count}",
                ],
                gaps=[
                    "centralized production log sink",
                    "alert evidence",
                    "tamper-resistance evidence",
                ],
                next_actions=[
                    "ship production logs to monitored storage",
                    "attach alert history to monthly review",
                ],
            ),
            SecurityControlEvidence(
                control_id="CC7.3",
                control_name="Incident response",
                status="partial",
                evidence_refs=[
                    "SECURITY.md",
                    "docs/breach-response-runbook.md",
                ],
                evidence_tasks=[
                    "docs/incident-tabletop-template.md",
                ],
                gaps=[
                    "tabletop exercise evidence",
                    "incident ticket examples",
                    "notification decision log",
                ],
                next_actions=[
                    "run tabletop exercise",
                    "save post-incident review template",
                ],
            ),
            SecurityControlEvidence(
                control_id="CC8.1",
                control_name="Change management",
                status="needs_evidence",
                evidence_refs=[
                    "tests/",
                    "git history",
                ],
                gaps=[
                    "branch protection evidence",
                    "review approval evidence",
                    "release checklist evidence",
                ],
                next_actions=[
                    "document release process",
                    "export merged PR and CI evidence per release",
                ],
            ),
            SecurityControlEvidence(
                control_id="A1.2",
                control_name="Availability, backup, and disaster recovery",
                status="partial",
                evidence_refs=[
                    "docs/backup-restore-dr-plan.md",
                ],
                evidence_tasks=[
                    "docs/backup-restore-dr-plan.md",
                ],
                gaps=[
                    "backup policy",
                    "restore test evidence",
                    "RTO/RPO approval",
                ],
                next_actions=[
                    "define backup schedule",
                    "run and record restore test",
                ],
            ),
            SecurityControlEvidence(
                control_id="CC6.6",
                control_name="Vulnerability management",
                status="partial",
                evidence_refs=[
                    "docs/vulnerability-management-program.md",
                ],
                evidence_tasks=[
                    "docs/vulnerability-management-program.md",
                ],
                gaps=[
                    "dependency scanning evidence",
                    "SAST/DAST evidence",
                    "patch SLA evidence",
                ],
                next_actions=[
                    "enable dependency and code scanning",
                    "record remediation SLA and owner",
                ],
            ),
            SecurityControlEvidence(
                control_id="P1.1",
                control_name="Privacy commitments and processing inventory",
                status="partial",
                evidence_refs=[
                    "docs/privacy-data-map.md",
                    "docs/data-subject-request-workflow.md",
                    "complyos/services/privacy.py",
                    f"evidence_entry_count:{evidence_entry_count}",
                ],
                gaps=[
                    "counsel-approved privacy commitments",
                    "customer-specific DPA execution",
                    "region-specific transfer evidence",
                ],
                next_actions=[
                    "review privacy artifacts with counsel",
                    "attach executed customer terms when available",
                ],
            ),
        ]
