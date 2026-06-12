"""Guardrails for Phase A privacy/program compliance artifacts."""

from __future__ import annotations

from pathlib import Path

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.readiness import ReadinessService

REQUIRED_ARTIFACTS = {
    "docs/privacy-data-map.md": [
        "Data categories",
        "Processing purposes",
        "Source systems",
        "Retention",
        "Data subject rights",
    ],
    "docs/data-retention-deletion-policy.md": [
        "Retention schedule",
        "Deletion workflow",
        "Legal hold",
        "Audit evidence",
    ],
    "docs/data-subject-request-workflow.md": [
        "Intake",
        "Identity verification",
        "Export",
        "Correction",
        "Deletion",
    ],
    "docs/subprocessors.md": [
        "Subprocessor register",
        "Review cadence",
        "Customer notice",
        "No production subprocessors approved",
    ],
    "docs/dpa-template.md": [
        "Data Processing Addendum",
        "Controller",
        "Processor",
        "Security measures",
        "Subprocessors",
    ],
    "docs/breach-response-runbook.md": [
        "Breach response",
        "Triage",
        "Containment",
        "Notification assessment",
        "Post-incident review",
    ],
}

REQUIRED_GOVERNANCE_ARTIFACTS = {
    "docs/ai-governance-impact-assessment.md": [
        "AI impact assessment",
        "Proposal-only",
        "Human review",
        "Employment decision boundary",
    ],
    "docs/school-vendor-privacy-accessibility-packet.md": [
        "School vendor packet",
        "Student data",
        "FERPA",
        "COPPA",
        "Accessibility",
    ],
    "docs/fcra-employment-decision-boundary.md": [
        "FCRA boundary",
        "background screening",
        "employment eligibility",
        "Do not use",
    ],
}

REQUIRED_SECURITY_OPS_ARTIFACTS = {
    "docs/access-review-procedure.md": [
        "Access review",
        "SSO",
        "MFA",
        "Joiner",
        "Leaver",
    ],
    "docs/vulnerability-management-program.md": [
        "Vulnerability management",
        "Dependency scanning",
        "Patch SLA",
        "Remediation evidence",
    ],
    "docs/backup-restore-dr-plan.md": [
        "Backup",
        "Restore test",
        "RTO",
        "RPO",
        "Disaster recovery",
    ],
    "docs/incident-tabletop-template.md": [
        "Incident tabletop",
        "Scenario",
        "Participants",
        "Lessons learned",
    ],
}


def test_phase_a_privacy_program_artifacts_exist_and_cover_required_topics() -> None:
    for relative_path, required_phrases in REQUIRED_ARTIFACTS.items():
        path = Path(relative_path)

        assert path.exists(), f"missing artifact: {relative_path}"
        text = path.read_text(encoding="utf-8")
        for phrase in required_phrases:
            assert phrase in text, f"{relative_path} missing {phrase!r}"


def test_governance_program_artifacts_exist_and_cover_required_topics() -> None:
    for relative_path, required_phrases in REQUIRED_GOVERNANCE_ARTIFACTS.items():
        path = Path(relative_path)

        assert path.exists(), f"missing artifact: {relative_path}"
        text = path.read_text(encoding="utf-8")
        for phrase in required_phrases:
            assert phrase in text, f"{relative_path} missing {phrase!r}"


def test_security_operations_artifacts_exist_and_cover_required_topics() -> None:
    for relative_path, required_phrases in REQUIRED_SECURITY_OPS_ARTIFACTS.items():
        path = Path(relative_path)

        assert path.exists(), f"missing artifact: {relative_path}"
        text = path.read_text(encoding="utf-8")
        for phrase in required_phrases:
            assert phrase in text, f"{relative_path} missing {phrase!r}"


def test_readiness_inventory_tracks_phase_a_privacy_program_artifacts(tmp_path) -> None:
    service = ReadinessService(LocalRepository(str(tmp_path / "ready.db")))
    report = service.check(default_local_context(surface="cli"))
    control_ids = {control.id for control in report.controls}

    assert "privacy-data-map" in control_ids
    assert "data-retention-deletion" in control_ids
    assert "data-subject-request-workflow" in control_ids
    assert "dpa-subprocessor-package" in control_ids
    assert "breach-response-runbook" in control_ids
    assert "ai-impact-assessment" in control_ids
    assert "school-vendor-privacy-accessibility" in control_ids
    assert "fcra-employment-decision-boundary" in control_ids
    assert "access-review-procedure" in control_ids
    assert "vulnerability-management-program" in control_ids
    assert "backup-restore-dr-plan" in control_ids
    assert "incident-tabletop-template" in control_ids
