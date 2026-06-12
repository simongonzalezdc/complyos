"""Security evidence-room workflow tests."""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.security_evidence import SecurityEvidenceService


def test_security_evidence_packet_maps_soc2_controls_without_claims(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "security-evidence.db"))
    context = default_local_context(role="compliance_manager")

    packet = SecurityEvidenceService(repo).collect_packet(
        context,
        period="2026-Q2",
    )

    assert packet.posture == "readiness_only"
    assert packet.period == "2026-Q2"
    control_ids = {control.control_id for control in packet.controls}
    assert {"CC6.1", "CC7.2", "CC7.3", "A1.2"}.issubset(control_ids)
    assert "SOC 2 certified" not in packet.model_dump_json()
    assert repo.list_action_logs()[0]["action"] == "security.evidence.packet"


def test_security_evidence_packet_includes_operational_evidence_tasks(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "security-tasks.db"))
    context = default_local_context(role="compliance_manager")

    packet = SecurityEvidenceService(repo).collect_packet(context, period="2026-Q2")
    controls = {control.control_id: control for control in packet.controls}

    assert "docs/access-review-procedure.md" in controls["CC6.1"].evidence_tasks
    assert "docs/vulnerability-management-program.md" in controls["CC6.6"].evidence_tasks
    assert "docs/backup-restore-dr-plan.md" in controls["A1.2"].evidence_tasks
    assert "docs/incident-tabletop-template.md" in controls["CC7.3"].evidence_tasks


def test_security_evidence_packet_counts_only_current_tenant_evidence(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "security-tenant-evidence.db"))
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")
    repo.append_evidence_entry(
        tenant_id="tenant-a",
        query_type="audit",
        query_params={"tenant_id": "tenant-a"},
        raw_data_hash="raw-a",
        transformation_steps=["hash"],
        output_hash="out-a",
        output_summary="tenant a evidence",
    )
    repo.append_evidence_entry(
        tenant_id="tenant-b",
        query_type="audit",
        query_params={"tenant_id": "tenant-b"},
        raw_data_hash="raw-b",
        transformation_steps=["hash"],
        output_hash="out-b",
        output_summary="tenant b evidence",
    )

    packet = SecurityEvidenceService(repo).collect_packet(context, period="2026-Q2")

    assert packet.summary["evidence_entries"] == 1
