"""Governance readiness packet for HR AI, schools, accessibility, and FCRA boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from complyos.core.repository import LocalRepository
from complyos.services.context import PERM_GOVERNANCE_READ, ActorContext, require_permission


class GovernanceArea(BaseModel):
    area_id: str
    title: str
    status: str
    artifact: str
    guardrails: list[str] = Field(default_factory=list)
    remaining_external_work: list[str] = Field(default_factory=list)
    buyer_questions_answered: list[str] = Field(default_factory=list)


class GovernancePacket(BaseModel):
    tenant_id: str
    lane: str
    posture: str = "readiness_only"
    generated_at: datetime
    summary: dict[str, int] = Field(default_factory=dict)
    areas: list[GovernanceArea]
    actor_context: dict[str, str] = Field(default_factory=dict)


class GovernancePacketService:
    """Build a readiness-only packet for non-SOC2 governance reviews."""

    def __init__(
        self,
        repository: LocalRepository | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.repository = repository or LocalRepository()
        self.project_root = project_root or Path.cwd()

    def collect_packet(
        self,
        context: ActorContext,
        *,
        lane: str = "workforce",
    ) -> GovernancePacket:
        require_permission(context, PERM_GOVERNANCE_READ)
        if lane not in {"workforce", "campus", "combined"}:
            raise ValueError("lane must be workforce, campus, or combined")
        generated_at = datetime.now(UTC)
        areas = self._areas()
        summary = {
            "areas_total": len(areas),
            "areas_partial": sum(1 for area in areas if area.status == "partial"),
            "areas_missing": sum(1 for area in areas if area.status == "missing"),
        }
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="governance.packet.collect",
            object_type="governance_packet",
            object_id=lane,
            result="readiness_only",
            request_id=context.request_id,
            metadata=summary,
        )
        return GovernancePacket(
            tenant_id=context.tenant_id,
            lane=lane,
            generated_at=generated_at,
            summary=summary,
            areas=areas,
            actor_context=context.public_dict(),
        )

    def _areas(self) -> list[GovernanceArea]:
        return [
            GovernanceArea(
                area_id="ai-impact-assessment",
                title="HR and learning AI impact assessment",
                status=self._artifact_status("docs/ai-governance-impact-assessment.md"),
                artifact="docs/ai-governance-impact-assessment.md",
                guardrails=[
                    "AI remains proposal-only unless a reviewed workflow says otherwise.",
                    "No automated employment, discipline, compensation, or opportunity decisions.",
                    "Human approval and provenance are required for mapping suggestions.",
                ],
                remaining_external_work=[
                    "counsel review for target regions",
                    "customer-specific AI disclosure language",
                    "final human-review operating procedure",
                ],
                buyer_questions_answered=[
                    "Does AI mutate compliance truth?",
                    "Can AI decide employment outcomes?",
                    "What evidence proves human review?",
                ],
            ),
            GovernanceArea(
                area_id="school-vendor-privacy-accessibility",
                title="School vendor privacy and accessibility packet",
                status=self._artifact_status(
                    "docs/school-vendor-privacy-accessibility-packet.md"
                ),
                artifact="docs/school-vendor-privacy-accessibility-packet.md",
                guardrails=[
                    "Route student and parent requests through the school customer.",
                    "Keep student-data terms customer-specific.",
                    "Treat accessibility evidence as procurement evidence, not marketing copy.",
                ],
                remaining_external_work=[
                    "school counsel terms",
                    "state-specific student privacy review",
                    "VPAT or equivalent accessibility assessment",
                ],
                buyer_questions_answered=[
                    "How are student/parent requests routed?",
                    "What terms are needed before school launch?",
                    "What accessibility evidence is still needed?",
                ],
            ),
            GovernanceArea(
                area_id="fcra-employment-decision-boundary",
                title="FCRA and employment-decision boundary",
                status=self._artifact_status("docs/fcra-employment-decision-boundary.md"),
                artifact="docs/fcra-employment-decision-boundary.md",
                guardrails=[
                    (
                        "Do not market reports as employment eligibility or "
                        "background-screening reports."
                    ),
                    (
                        "Do not rank people for hiring, firing, promotion, discipline, "
                        "or compensation."
                    ),
                    "Escalate before adding any people-decision workflow.",
                ],
                remaining_external_work=[
                    "sales/legal enablement review",
                    "customer contract boundary language",
                    "product-review gate for any future people-decision feature",
                ],
                buyer_questions_answered=[
                    "Is this a background-screening product?",
                    "Can outputs be used to rank employees?",
                    "What happens if a buyer wants decisioning?",
                ],
            ),
        ]

    def _artifact_status(self, relative_path: str) -> str:
        return "partial" if (self.project_root / relative_path).exists() else "missing"
