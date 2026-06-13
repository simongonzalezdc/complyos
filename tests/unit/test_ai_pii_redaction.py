"""AI proposal layer PII redaction tests (plan §11.3).

When a proposal is created, PII in the source input must be redacted before it
reaches the hashed prompt / model-facing payload. Only headers/structure and
non-PII may influence the input_hash/prompt_hash preimage.
"""

from __future__ import annotations

import json

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import AIProposalService, redact_pii
from complyos.services.context import default_local_context

PII_ROWS = [
    {
        "Learner Name": "Jane Smith",
        "Email": "jane@corp.com",
        "Employee ID": "E-00471",
        "SSN": "123-45-6789",
        "Course ID": "SEC-101",
        "Status": "completed",
    },
    {
        "Learner Name": "Bob Jones",
        "Email": "bob.jones@corp.com",
        "Employee ID": "E-00984",
        "SSN": "987-65-4321",
        "Course ID": "SEC-102",
        "Status": "in_progress",
    },
]

RAW_PII_VALUES = [
    "Jane Smith",
    "jane@corp.com",
    "E-00471",
    "123-45-6789",
    "Bob Jones",
    "bob.jones@corp.com",
    "E-00984",
    "987-65-4321",
]


def test_redact_pii_helper_masks_values_but_keeps_structure() -> None:
    redacted, policy = redact_pii(PII_ROWS[0])

    serialized = json.dumps(redacted)
    for raw in ("Jane Smith", "jane@corp.com", "E-00471", "123-45-6789"):
        assert raw not in serialized
    # Non-PII structure survives.
    assert redacted["Course ID"] == "SEC-101"
    assert redacted["Status"] == "completed"
    # The policy reflects what was actually masked (not a static string).
    assert policy["masked_count"] >= 4
    assert any("email" in field.lower() for field in policy["masked_fields"])
    assert any("name" in field.lower() for field in policy["masked_fields"])


def test_proposal_does_not_leak_pii_into_stored_payload_or_hash(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ai-pii.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    headers = list(PII_ROWS[0].keys())
    proposal = service.propose_mapping(context, headers=headers, sample_rows=PII_ROWS)

    stored = repo.get_ai_proposal(proposal.proposal_id)
    assert stored is not None

    # The full stored record (output + provenance) must not contain raw PII.
    haystack = json.dumps(stored, default=str)
    for raw in RAW_PII_VALUES:
        assert raw not in haystack, f"raw PII leaked into stored proposal: {raw!r}"

    # The hash preimage the service exposes must not contain raw PII either.
    preimage = service.last_hash_preimage()
    preimage_text = json.dumps(preimage, default=str)
    for raw in RAW_PII_VALUES:
        assert raw not in preimage_text, f"raw PII leaked into hash preimage: {raw!r}"

    # redaction_policy records the masking that actually happened.
    policy = proposal.provenance["redaction_policy"]
    assert isinstance(policy, dict)
    assert policy["masked_count"] >= len(RAW_PII_VALUES)
    assert policy["sample_rows_redacted"] is True


def test_headers_only_proposal_records_no_record_redaction(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ai-headers.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    proposal = service.propose_mapping(context, headers=["User ID", "Course ID", "Status"])

    policy = proposal.provenance["redaction_policy"]
    assert isinstance(policy, dict)
    assert policy["sample_rows_redacted"] is False
    assert policy["masked_count"] == 0
