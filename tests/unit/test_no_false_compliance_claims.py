"""Guardrail against unsupported compliance/certification claims in public docs."""

from __future__ import annotations

import re
from pathlib import Path

PUBLIC_TEXT_FILES = [
    Path("README.md"),
    Path("COMMERCIAL-LICENSE.md"),
    Path("docs/pricing.md"),
    Path("docs/access-review-procedure.md"),
    Path("docs/index.html"),
    Path("docs/agent-surface.md"),
    Path("docs/ai-governance-impact-assessment.md"),
    Path("docs/backup-restore-dr-plan.md"),
    Path("docs/breach-response-runbook.md"),
    Path("docs/compliance-readiness.md"),
    Path("docs/data-retention-deletion-policy.md"),
    Path("docs/data-subject-request-workflow.md"),
    Path("docs/dpa-template.md"),
    Path("docs/fcra-employment-decision-boundary.md"),
    Path("docs/hr-people-analytics-compliance-audit.md"),
    Path("docs/privacy-data-map.md"),
    Path("docs/school-vendor-privacy-accessibility-packet.md"),
    Path("docs/security-evidence-control-matrix.md"),
    Path("docs/subprocessors.md"),
    Path("docs/incident-tabletop-template.md"),
    Path("docs/vulnerability-management-program.md"),
    Path("llms.txt"),
]

FORBIDDEN_PATTERNS = [
    r"\bSOC\s*2\s+compliant\b",
    r"\bSOC\s*2\s+certified\b",
    r"\bFERPA\s+compliant\b",
    r"\bCOPPA\s+compliant\b",
    r"\bGDPR\s+compliant\b",
    r"\bLGPD\s+compliant\b",
    r"\bPIPEDA\s+compliant\b",
]


def test_public_docs_do_not_make_unsupported_compliance_claims() -> None:
    for path in PUBLIC_TEXT_FILES:
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            assert re.search(pattern, text, flags=re.IGNORECASE) is None, f"{path}: {pattern}"


def test_hr_people_analytics_audit_covers_core_lanes() -> None:
    text = Path("docs/hr-people-analytics-compliance-audit.md").read_text(encoding="utf-8")

    for expected in [
        "Vendor security assurance",
        "Privacy: GDPR",
        "HR / employment law",
        "AI governance",
        "Education privacy",
        "FCRA / background screening",
        "Accessibility",
    ]:
        assert expected in text
