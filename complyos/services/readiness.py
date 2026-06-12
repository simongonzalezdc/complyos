"""Readiness checks for enterprise/school procurement posture.

This is control readiness, not a certification engine and not legal advice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from complyos.core.repository import LocalRepository
from complyos.services.context import PERM_READINESS_READ, ActorContext, require_permission


class ReadinessControl(BaseModel):
    id: str
    area: str
    title: str
    status: str
    owner: str
    artifact: str
    retention: str
    frameworks: list[str] = Field(default_factory=list)
    external_claim_allowed: bool = False
    notes: str | None = None


class ReadinessReport(BaseModel):
    generated_at: datetime
    tenant_id: str
    track: str
    posture: str
    summary: dict[str, int]
    controls: list[ReadinessControl]
    global_regulation_watchlist: list[str]
    forbidden_claims: list[str]
    actor_context: dict[str, str]


class ReadinessService:
    """Build a concrete readiness inventory for buyers/auditors."""

    def __init__(
        self,
        repository: LocalRepository | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.repository = repository or LocalRepository()
        self.project_root = project_root or Path.cwd()

    def check(self, context: ActorContext) -> ReadinessReport:
        require_permission(context, PERM_READINESS_READ)
        controls = self._controls(context)
        summary: dict[str, int] = {}
        for control in controls:
            summary[control.status] = summary.get(control.status, 0) + 1
        return ReadinessReport(
            generated_at=datetime.now(UTC),
            tenant_id=context.tenant_id,
            track=context.track,
            posture=(
                "readiness-only: ComplyOS maps controls and artifacts, but does not claim "
                "SOC 2, FERPA, COPPA, GDPR, or regional legal certification."
            ),
            summary=summary,
            controls=controls,
            global_regulation_watchlist=[
                "SOC 2 Trust Services Criteria",
                "FERPA / COPPA school-vendor review",
                "WCAG 2.2 AA and ADA public-sector expectations",
                "GDPR / UK GDPR / LGPD / PIPEDA / APP / PDPA / APPI / PIPA / DPDP / PIPL / POPIA",
                "EU AI Act and automated-decision transparency considerations",
            ],
            forbidden_claims=[
                "SOC 2 compliant",
                "SOC 2 certified",
                "FERPA compliant",
                "COPPA compliant",
                "GDPR compliant",
                "global privacy compliant",
            ],
            actor_context=context.public_dict(),
        )

    def _controls(self, context: ActorContext) -> list[ReadinessControl]:
        docs_exist = (self.project_root / "docs").exists()
        security_exists = (self.project_root / "SECURITY.md").exists()
        release_exists = (self.project_root / "docs" / "release-checklist.md").exists()
        return [
            ReadinessControl(
                id="access-control-service-authz",
                area="security",
                title="Service-layer actor context and permissions",
                status="designed",
                owner="product/security",
                artifact="complyos/services/context.py",
                retention="source-controlled; review every release",
                frameworks=["SOC2 Security", "NIST AC", "OWASP API"],
                notes=f"tenant={context.tenant_id}; surface={context.surface}",
            ),
            ReadinessControl(
                id="audit-action-log",
                area="security",
                title="Actor/action/object/result/request audit log",
                status="partial",
                owner="engineering",
                artifact="audit_action_logs table",
                retention="tenant policy; minimum buyer contract requirement",
                frameworks=["SOC2 Security", "SOC2 Processing Integrity"],
            ),
            ReadinessControl(
                id="gated-import-lifecycle",
                area="data-integrity",
                title="CSV/import preview, quarantine, decision, promotion",
                status="designed",
                owner="learning-ops",
                artifact="complyos/services/imports.py",
                retention="raw hash plus row decisions retained by tenant policy",
                frameworks=["SOC2 Processing Integrity", "Privacy data minimization"],
            ),
            ReadinessControl(
                id="ai-proposal-only",
                area="ai-governance",
                title="AI proposals cannot mutate compliance truth",
                status="designed",
                owner="product/security",
                artifact="complyos/services/ai_proposals.py",
                retention="proposal/provenance retained by tenant policy",
                frameworks=["EU AI Act readiness", "OWASP LLM"],
            ),
            ReadinessControl(
                id="incident-response-runbook",
                area="security",
                title="Security contact and incident response path",
                status="partial" if security_exists else "missing",
                owner="security",
                artifact="SECURITY.md",
                retention="source-controlled; tabletop every 6-12 months",
                frameworks=["SOC2 Security", "NIST IR"],
            ),
            ReadinessControl(
                id="change-management-release-checklist",
                area="operations",
                title="Release checklist and verification gates",
                status="partial" if release_exists else "missing",
                owner="engineering",
                artifact="docs/release-checklist.md",
                retention="per release",
                frameworks=["SOC2 Change Management", "SSDF"],
            ),
            ReadinessControl(
                id="school-privacy-accessibility-readiness",
                area="education",
                title="FERPA/COPPA/accessibility readiness notes",
                status="partial" if docs_exist else "missing",
                owner="product/legal-review",
                artifact="docs/compliance-readiness.md",
                retention="review with counsel before school procurement use",
                frameworks=["FERPA", "COPPA", "WCAG 2.2 AA", "ADA Title II"],
            ),
            ReadinessControl(
                id="global-privacy-control-matrix",
                area="privacy",
                title="Global privacy/regional readiness matrix",
                status="partial" if docs_exist else "missing",
                owner="privacy/legal-review",
                artifact="docs/compliance-readiness.md",
                retention="review quarterly or when entering new region",
                frameworks=["GDPR", "UK GDPR", "LGPD", "PIPEDA", "APPI", "PIPL", "POPIA"],
            ),
        ]
