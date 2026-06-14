"""WP15b: deterministic, proposal-only AI proposal types.

Each type (anomaly summary, gap explanation, remediation message, duplicate
clustering) must: produce a PROPOSED proposal with deterministic-local
provenance, stay proposal-only (state_mutation_allowed False; no compliance
records written), reference learners only by non-PII fields, and flow through
the same approve/reject lifecycle as field mapping.
"""

from __future__ import annotations

import json

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import AIProposalService
from complyos.services.context import default_local_context


def _service(tmp_path, name: str) -> tuple[AIProposalService, LocalRepository]:
    repo = LocalRepository(str(tmp_path / name))
    return AIProposalService(repo), repo


def test_anomaly_summary_counts_codes_and_is_proposal_only(tmp_path) -> None:
    service, repo = _service(tmp_path, "anomaly.db")
    context = default_local_context(surface="cli")

    result = service.propose_anomaly_summary(
        context,
        issues=[
            {"code": "STALE_EXPORT"},
            {"code": "BACKDATED_DATE"},
            {"code": "BACKDATED_DATE"},
        ],
    )

    assert result.proposal_type == "anomaly_summary"
    assert result.status == "PROPOSED"
    assert result.output["state_mutation_allowed"] is False
    assert result.output["total_signals"] == 3
    assert result.output["counts_by_code"]["BACKDATED_DATE"] == 2
    assert result.provenance["model_provider"] == "deterministic-local"
    # proposal-only: nothing written to compliance state
    assert repo.list_learning_records() == []


def test_gap_explanation_is_pii_free_and_approvable(tmp_path) -> None:
    service, repo = _service(tmp_path, "gap.db")
    context = default_local_context(surface="cli")

    result = service.propose_gap_explanation(
        context,
        user_id="u4",
        department="HR",
        missing_courses=["Information Security Basics"],
        days_overdue=10,
        severity="high",
    )
    approved = service.approve(context, result.proposal_id)

    assert result.proposal_type == "gap_explanation"
    assert "u4" in result.output["explanation"]
    assert "Information Security Basics" in result.output["explanation"]
    assert "10 day" in result.output["explanation"]
    assert approved.status == "APPROVED"
    # approval records review; it does not mutate compliance truth
    assert repo.list_learning_records() == []


def test_remediation_message_is_pii_free_draft(tmp_path) -> None:
    service, _ = _service(tmp_path, "msg.db")
    context = default_local_context(surface="cli")

    result = service.propose_remediation_message(
        context,
        user_id="u2",
        missing_courses=["Respectful Environment", "Information Security Basics"],
        deadline="2026-07-01",
    )

    assert result.proposal_type == "remediation_message"
    draft = result.output["message_draft"]
    assert "u2" in draft
    assert "2026-07-01" in draft
    assert result.output["state_mutation_allowed"] is False


def test_duplicate_clustering_groups_by_hashed_identity_without_pii(tmp_path) -> None:
    service, _ = _service(tmp_path, "dupe.db")
    context = default_local_context(surface="cli")

    rows = [
        {"employee_id": "E001", "name": "Alice Smith", "course_id": "c1"},
        {"employee_id": "E001", "name": "Alice Smith", "course_id": "c1"},  # dup
        {"employee_id": "E002", "name": "Bob Jones", "course_id": "c1"},
    ]
    result = service.propose_duplicate_clustering(context, rows=rows)

    assert result.proposal_type == "duplicate_clustering"
    assert result.output["rows_examined"] == 3
    assert result.output["duplicate_groups"] == 1
    cluster = result.output["duplicate_clusters"][0]
    assert cluster["size"] == 2
    assert cluster["row_numbers"] == [0, 1]

    # The raw PII must not appear anywhere in the stored output or the hash
    # preimage — duplicates are grouped by a hash signature, not the raw name.
    stored = json.dumps(result.output) + json.dumps(service.last_hash_preimage())
    assert "Alice" not in stored
    assert "Smith" not in stored
    assert "E001" not in stored


def test_new_types_do_not_expose_mutating_methods() -> None:
    # The forbidden-mutation guarantee (WP15a) still holds for the WP15b types.
    for forbidden in (
        "mark_compliant",
        "promote",
        "promote_import",
        "execute_remediation",
        "remediate",
        "change_rules",
        "update_rules",
    ):
        assert not hasattr(AIProposalService, forbidden)
