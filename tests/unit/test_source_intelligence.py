from __future__ import annotations

from complyos.microlearning import MicrolearningAdapter
from complyos.regwatch import RegWatchAdapter
from complyos.source_intel import (
    SourceDefinition,
    SourceIntelEngine,
    SourceSnapshot,
    SourceType,
    build_snapshot,
)


def test_shared_engine_routes_same_snapshot_to_regwatch_and_microlearning() -> None:
    source = SourceDefinition(
        id="california-civil-rights",
        name="California Civil Rights Department",
        url="https://calcivilrights.ca.gov/",
        source_type=SourceType.OFFICIAL_REGULATOR,
        authority="official",
        jurisdictions=["US-CA"],
        topics=["harassment prevention", "manager training"],
    )
    snapshot = build_snapshot(
        source,
        title="Updated workplace training guidance",
        text=(
            "New guidance effective January 1 says employers must provide harassment "
            "prevention training. Managers should use scenario-based practice and a "
            "short checklist to reinforce respectful feedback skills."
        ),
    )

    engine = SourceIntelEngine(adapters=[RegWatchAdapter(), MicrolearningAdapter()])
    proposals = engine.evaluate([source], [snapshot])

    assert {proposal.signal.signal_type for proposal in proposals} == {
        "regulatory_change",
        "microlearning_opportunity",
    }
    assert all(proposal.approval_state == "needs_review" for proposal in proposals)
    assert all(proposal.source_hash == snapshot.content_hash for proposal in proposals)
    assert all(proposal.source_url == source.url for proposal in proposals)
    assert all(
        proposal.evidence_chain == [
            "source_registry",
            "source_snapshot",
            proposal.adapter_name,
            "human_approval",
        ]
        for proposal in proposals
    )


def test_regwatch_adapter_creates_obligation_proposal_for_official_change() -> None:
    source = SourceDefinition(
        id="osha",
        name="OSHA",
        url="https://www.osha.gov/laws-regs",
        source_type=SourceType.OFFICIAL_REGULATOR,
        authority="official",
        jurisdictions=["US"],
        topics=["workplace safety", "required training"],
    )
    snapshot = SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title="Final rule updates required safety training",
        text="A final rule says covered employers must train workers by July 1, 2027.",
    )

    proposals = RegWatchAdapter().evaluate(source, snapshot)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.signal.signal_type == "regulatory_change"
    assert proposal.signal.jurisdictions == ["US"]
    assert proposal.signal.score >= 0.8
    assert proposal.approval_state == "needs_review"
    assert proposal.suggested_action["action_type"] == "review_obligation"
    assert "must train workers" in proposal.signal.evidence_quote.lower()


def test_microlearning_adapter_creates_module_proposal_from_teachable_source() -> None:
    source = SourceDefinition(
        id="atd-feedback-guide",
        name="Association for Talent Development",
        url="https://www.td.org/",
        source_type=SourceType.PROFESSIONAL_BODY,
        authority="trusted",
        jurisdictions=[],
        topics=["manager enablement", "feedback skills"],
    )
    snapshot = SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title="New guide: managers can practice better feedback",
        text=(
            "Research shows managers improve feedback quality when they use examples, "
            "practice with scenarios, and follow a checklist before one-on-ones."
        ),
    )

    proposals = MicrolearningAdapter().evaluate(source, snapshot)

    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal.signal.signal_type == "microlearning_opportunity"
    assert proposal.approval_state == "needs_review"
    assert proposal.suggested_action["action_type"] == "draft_microlearning_module"
    assert proposal.suggested_action["module"]["duration_minutes"] == 5
    assert proposal.suggested_action["module"]["learning_objectives"]
    assert proposal.suggested_action["module"]["check_for_understanding"]
    assert proposal.source_url == source.url


def test_snapshot_hash_changes_only_when_source_text_changes() -> None:
    source = SourceDefinition(
        id="internal-policy-upload",
        name="Internal policy upload",
        url="file://policy.md",
        source_type=SourceType.INTERNAL_UPLOAD,
        authority="internal",
        jurisdictions=["US"],
        topics=["policy"],
    )

    first = build_snapshot(source, title="Policy", text="Employees must complete training.")
    duplicate = build_snapshot(source, title="Policy", text="Employees must complete training.")
    changed = build_snapshot(
        source, title="Policy", text="Employees must complete training annually."
    )

    assert first.content_hash == duplicate.content_hash
    assert first.content_hash != changed.content_hash
