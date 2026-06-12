"""Guardrail against unsupported compliance/certification claims in public docs."""

from __future__ import annotations

import re
from pathlib import Path

PUBLIC_TEXT_FILES = [
    Path("README.md"),
    Path("docs/index.html"),
    Path("docs/agent-surface.md"),
    Path("docs/compliance-readiness.md"),
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
