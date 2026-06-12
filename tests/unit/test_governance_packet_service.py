"""Governance packet workflow tests."""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.governance import GovernancePacketService


def test_governance_packet_maps_ai_school_and_fcra_boundaries(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "governance.db"))
    context = default_local_context(role="compliance_manager")

    packet = GovernancePacketService(repo).collect_packet(
        context,
        lane="campus",
    )

    assert packet.posture == "readiness_only"
    assert packet.lane == "campus"
    area_ids = {area.area_id for area in packet.areas}
    assert {
        "ai-impact-assessment",
        "school-vendor-privacy-accessibility",
        "fcra-employment-decision-boundary",
    }.issubset(area_ids)
    assert "bias-free AI" not in packet.model_dump_json()
    assert repo.list_action_logs()[0]["action"] == "governance.packet.collect"
