from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples" / "learningops-suite"
DOCS = ROOT / "docs" / "demos"
REGWATCH_SOURCE_REQUIRED_FIELDS = {
    "source_id",
    "source_name",
    "jurisdiction",
    "jurisdiction_level",
    "agency_or_body",
    "source_type",
    "primary_url",
    "api_or_feed_url",
    "access_model",
    "parser_status",
    "domain_tags",
    "last_verified_at",
    "coverage_notes",
    "known_gaps",
    "human_owner_role",
    "allowed_outputs",
}
REGWATCH_ALERT_REQUIRED_FIELDS = {
    "proposal_id",
    "source_item_ids",
    "watch_profile_id",
    "relevance_rationale",
    "confidence",
    "training_impact_summary",
    "suggested_actions",
    "human_review_status",
    "coverage_disclosure",
    "created_at",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_training_from_scratch_demo_has_required_provenance_and_approval_gate() -> None:
    proposal = _json(EXAMPLES / "training-from-scratch" / "regwatch-alert-proposal.json")
    needs = _json(EXAMPLES / "training-from-scratch" / "needs-analysis.json")
    design = _json(EXAMPLES / "training-from-scratch" / "module-design.json")
    roster = _csv_rows(EXAMPLES / "training-from-scratch" / "rollout-roster.csv")

    assert proposal["synthetic"] is True
    assert proposal["human_review_status"] == "triage_needed"
    assert proposal["source_provenance"]["source_url"].startswith("https://www.osha.gov/")
    assert proposal["source_provenance"]["coverage_gaps"]
    assert "No rule" in proposal["coverage_disclosure"]
    assert needs["approval_required_before_design"] is True
    assert design["maturity"] == "synthetic_demo"
    assert "approve before publishing" in design["human_approval_gate"].lower()
    assert roster
    assert {row["human_review_status"] for row in roster} == {"pending_approval"}


def test_regwatch_demo_fixtures_match_documented_required_contract_fields() -> None:
    registry = _json(ROOT / "docs" / "regwatch-source-registry.example.json")
    proposal = _json(EXAMPLES / "training-from-scratch" / "regwatch-alert-proposal.json")

    assert registry["sources"]
    for source in registry["sources"]:
        assert source.keys() >= REGWATCH_SOURCE_REQUIRED_FIELDS
        assert source["last_verified_at"].endswith("Z")
        assert source["known_gaps"]

    assert proposal.keys() >= REGWATCH_ALERT_REQUIRED_FIELDS
    assert proposal["source_item_ids"]
    assert proposal["created_at"].endswith("Z")
    assert proposal["coverage_disclosure"]


def test_messy_training_ops_demo_has_csv_fallback_and_evidence_chain() -> None:
    messy = _csv_rows(EXAMPLES / "fix-messy-training-ops" / "messy-lms-export.csv")
    normalized = _csv_rows(EXAMPLES / "fix-messy-training-ops" / "normalized-roster.csv")
    gaps = _json(EXAMPLES / "fix-messy-training-ops" / "gap-analysis.json")
    drafts = _json(EXAMPLES / "fix-messy-training-ops" / "learner-support-drafts.json")
    brief = _json(EXAMPLES / "fix-messy-training-ops" / "manager-brief.json")

    assert len(messy) == 5
    assert len(normalized) == 4
    assert any(row["source_system"] == "csv_fallback" for row in messy)
    assert gaps["synthetic"] is True
    assert "human approval gate" in gaps["source_chain"]
    assert any("packet" in step for step in gaps["source_chain"])
    assert drafts["send_status"] == "draft_only"
    assert drafts["requires_human_approval"] is True
    assert "source export" in brief["evidence_chain"]
    assert "not proof of live tenant integration" in brief["coverage_disclosure"]


def test_demo_docs_and_fixtures_are_synthetic_only() -> None:
    checked_paths = [
        *EXAMPLES.rglob("*.json"),
        *EXAMPLES.rglob("*.csv"),
        *DOCS.rglob("*.md"),
    ]
    assert checked_paths
    forbidden_real_markers = [
        "@personal.example",
        "@real-employer.example",
        "@private-school.example",
    ]
    combined = "\n".join(path.read_text().lower() for path in checked_paths)
    assert "synthetic" in combined
    for marker in forbidden_real_markers:
        assert marker not in combined
