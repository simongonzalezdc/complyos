"""Readiness checks for enterprise/school procurement posture.

This is control readiness, not a certification engine and not legal advice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from complyos.core.repository import LocalRepository
from complyos.services.context import PERM_READINESS_READ, ActorContext, require_permission


class TenantMetadata(BaseModel):
    """Data-governance metadata surfaced for a tenant (plan §15 criterion).

    Maps the five buyer/auditor fields the readiness inventory must cover:
    data region, processing purpose, data categories, retention, subprocessors.
    """

    data_region: str | None = None
    processing_purpose: str | None = None
    data_categories: list[str] = Field(default_factory=list)
    retention_policy: dict[str, Any] = Field(default_factory=dict)
    subprocessor_profile: dict[str, Any] = Field(default_factory=dict)


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
    tenant_metadata: TenantMetadata = Field(default_factory=TenantMetadata)


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
        tenant_metadata = TenantMetadata(
            **self.repository.get_tenant_metadata(context.tenant_id)
        )
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
                "EEOC / ADA employment-decision and accommodation considerations",
                "NYC AEDT / Colorado AI Act / similar automated-decision rules",
                (
                    "FCRA boundary if reports are used for employment eligibility "
                    "or background screening"
                ),
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
            tenant_metadata=tenant_metadata,
        )

    def _controls(self, context: ActorContext) -> list[ReadinessControl]:
        docs_exist = (self.project_root / "docs").exists()
        security_exists = (self.project_root / "SECURITY.md").exists()
        release_exists = (self.project_root / "docs" / "release-checklist.md").exists()
        privacy_data_map_exists = (self.project_root / "docs" / "privacy-data-map.md").exists()
        retention_policy_exists = (
            self.project_root / "docs" / "data-retention-deletion-policy.md"
        ).exists()
        dsr_workflow_exists = (
            self.project_root / "docs" / "data-subject-request-workflow.md"
        ).exists()
        subprocessor_package_exists = (
            self.project_root / "docs" / "subprocessors.md"
        ).exists() and (self.project_root / "docs" / "dpa-template.md").exists()
        breach_runbook_exists = (
            self.project_root / "docs" / "breach-response-runbook.md"
        ).exists()
        ai_impact_assessment_exists = (
            self.project_root / "docs" / "ai-governance-impact-assessment.md"
        ).exists()
        school_vendor_packet_exists = (
            self.project_root / "docs" / "school-vendor-privacy-accessibility-packet.md"
        ).exists()
        fcra_boundary_exists = (
            self.project_root / "docs" / "fcra-employment-decision-boundary.md"
        ).exists()
        access_review_exists = (
            self.project_root / "docs" / "access-review-procedure.md"
        ).exists()
        vulnerability_program_exists = (
            self.project_root / "docs" / "vulnerability-management-program.md"
        ).exists()
        backup_dr_exists = (
            self.project_root / "docs" / "backup-restore-dr-plan.md"
        ).exists()
        tabletop_template_exists = (
            self.project_root / "docs" / "incident-tabletop-template.md"
        ).exists()
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
                retention=(
                    "raw rows/decisions purged by tenant policy after terminal batch; "
                    "hashes retained"
                ),
                frameworks=["SOC2 Processing Integrity", "Privacy data minimization"],
            ),
            ReadinessControl(
                id="ai-proposal-only",
                area="ai-governance",
                title="AI proposals cannot mutate compliance truth",
                status="designed",
                owner="product/security",
                artifact="complyos/services/ai_proposals.py",
                retention=(
                    "rejected/expired proposals purged by tenant policy; "
                    "approved evidence retained"
                ),
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
            ReadinessControl(
                id="privacy-data-map",
                area="privacy",
                title="Personal-data inventory and processing-purpose map",
                status="partial" if privacy_data_map_exists else "missing",
                owner="privacy/legal-review",
                artifact="docs/privacy-data-map.md",
                retention="review every release that changes data categories or source systems",
                frameworks=["GDPR Art. 30 readiness", "CCPA/CPRA inventory", "SOC2 Privacy"],
            ),
            ReadinessControl(
                id="data-retention-deletion",
                area="privacy",
                title="Retention schedule and deletion workflow",
                status="partial" if retention_policy_exists else "missing",
                owner="privacy/security",
                artifact="docs/data-retention-deletion-policy.md",
                retention="review quarterly and per customer contract",
                frameworks=["GDPR storage limitation", "CCPA/CPRA deletion", "SOC2 Security"],
            ),
            ReadinessControl(
                id="data-subject-request-workflow",
                area="privacy",
                title="Data subject access, export, correction, and deletion workflow",
                status="partial" if dsr_workflow_exists else "missing",
                owner="privacy/support",
                artifact="docs/data-subject-request-workflow.md",
                retention="review before entering new region or school lane",
                frameworks=["GDPR DSR", "CCPA/CPRA consumer rights", "FERPA request routing"],
            ),
            ReadinessControl(
                id="dpa-subprocessor-package",
                area="privacy",
                title="DPA template and subprocessor register",
                status="partial" if subprocessor_package_exists else "missing",
                owner="legal/vendor-management",
                artifact="docs/dpa-template.md; docs/subprocessors.md",
                retention="review before customer signature and before adding vendors",
                frameworks=["GDPR Art. 28 readiness", "CCPA/CPRA service provider terms"],
            ),
            ReadinessControl(
                id="breach-response-runbook",
                area="security",
                title="Breach response triage, containment, notification, and review runbook",
                status="partial" if breach_runbook_exists else "missing",
                owner="security/privacy/legal-review",
                artifact="docs/breach-response-runbook.md",
                retention="tabletop every 6-12 months and after incidents",
                frameworks=["SOC2 Security", "GDPR breach assessment", "state breach laws"],
            ),
            ReadinessControl(
                id="ai-impact-assessment",
                area="ai-governance",
                title="AI impact assessment and proposal-only boundary",
                status="partial" if ai_impact_assessment_exists else "missing",
                owner="product/security/legal-review",
                artifact="docs/ai-governance-impact-assessment.md",
                retention="review before any AI feature or model/provider change",
                frameworks=["EU AI Act readiness", "NYC AEDT boundary", "Colorado AI Act"],
            ),
            ReadinessControl(
                id="school-vendor-privacy-accessibility",
                area="education",
                title="School vendor privacy and accessibility procurement packet",
                status="partial" if school_vendor_packet_exists else "missing",
                owner="product/privacy/accessibility/legal-review",
                artifact="docs/school-vendor-privacy-accessibility-packet.md",
                retention="review before school pilot or procurement submission",
                frameworks=["FERPA", "COPPA", "WCAG 2.2 AA", "ADA Title II"],
            ),
            ReadinessControl(
                id="fcra-employment-decision-boundary",
                area="hr-governance",
                title="FCRA/background-screening and employment-decision boundary",
                status="partial" if fcra_boundary_exists else "missing",
                owner="product/legal-review/sales-enablement",
                artifact="docs/fcra-employment-decision-boundary.md",
                retention="review before positioning or people-decision feature changes",
                frameworks=["FCRA boundary", "EEOC", "ADA"],
            ),
            ReadinessControl(
                id="access-review-procedure",
                area="security",
                title="Access review, SSO/MFA, and joiner/mover/leaver procedure",
                status="partial" if access_review_exists else "missing",
                owner="security/it",
                artifact="docs/access-review-procedure.md",
                retention="quarterly review evidence plus employee lifecycle tickets",
                frameworks=["SOC2 Security", "NIST AC"],
            ),
            ReadinessControl(
                id="vulnerability-management-program",
                area="security",
                title="Dependency scanning, vulnerability triage, and patch SLA",
                status="partial" if vulnerability_program_exists else "missing",
                owner="security/engineering",
                artifact="docs/vulnerability-management-program.md",
                retention="scan output and remediation evidence per release/month",
                frameworks=["SOC2 Security", "SSDF", "OWASP"],
            ),
            ReadinessControl(
                id="backup-restore-dr-plan",
                area="availability",
                title="Backup, restore-test, RTO/RPO, and disaster recovery plan",
                status="partial" if backup_dr_exists else "missing",
                owner="security/infrastructure",
                artifact="docs/backup-restore-dr-plan.md",
                retention="backup job evidence and restore test every 6-12 months",
                frameworks=["SOC2 Availability", "NIST CP"],
            ),
            ReadinessControl(
                id="incident-tabletop-template",
                area="security",
                title="Incident tabletop exercise template",
                status="partial" if tabletop_template_exists else "missing",
                owner="security/privacy/legal-review",
                artifact="docs/incident-tabletop-template.md",
                retention="tabletop evidence every 6-12 months",
                frameworks=["SOC2 Security", "NIST IR"],
            ),
            ReadinessControl(
                id="hr-people-analytics-boundary",
                area="hr-governance",
                title="People-analytics boundary: no automated employment decisions",
                status=(
                    "partial"
                    if (
                        self.project_root / "docs" / "hr-people-analytics-compliance-audit.md"
                    ).exists()
                    else "missing"
                ),
                owner="product/legal-review",
                artifact="docs/hr-people-analytics-compliance-audit.md",
                retention=(
                    "review before any feature affects hiring, promotion, discipline, "
                    "compensation, or opportunity"
                ),
                frameworks=[
                    "EEOC",
                    "ADA",
                    "EU AI Act",
                    "NYC AEDT",
                    "Colorado AI Act",
                    "FCRA boundary",
                ],
            ),
        ]
