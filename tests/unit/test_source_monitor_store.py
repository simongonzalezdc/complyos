from __future__ import annotations

from complyos.microlearning import MicrolearningAdapter
from complyos.regwatch import RegWatchAdapter
from complyos.source_intel import SourceDefinition, SourceIntelEngine, SourceSnapshot, SourceType
from complyos.source_intel.clients import SourceFetchReport
from complyos.source_intel.monitor import SourceMonitor
from complyos.source_intel.store import SourceReviewStore


class FakeClient:
    def __init__(self, report: SourceFetchReport) -> None:
        self.report = report

    def fetch(self, source: SourceDefinition, *, query: str) -> SourceFetchReport:
        assert query == "training"
        return self.report


def test_source_monitor_runs_clients_and_returns_reviewable_proposals() -> None:
    source = SourceDefinition(
        id="free-source",
        name="Free Source",
        url="https://example.gov/source",
        source_type=SourceType.OFFICIAL_REGULATOR,
        authority="official",
        jurisdictions=["US"],
        topics=["safety training", "manager feedback"],
    )
    snapshot = SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title="Final rule and practice guide",
        text=(
            "A final rule says covered employers must train workers. "
            "Managers can use scenario practice, examples, and a checklist."
        ),
    )
    report = SourceFetchReport(source_id=source.id, snapshots=[snapshot], coverage_gaps=[])
    monitor = SourceMonitor(
        sources=[source],
        clients={source.id: FakeClient(report)},
        engine=SourceIntelEngine(adapters=[RegWatchAdapter(), MicrolearningAdapter()]),
    )

    run = monitor.run(query="training")

    assert run.source_count == 1
    assert run.snapshot_count == 1
    assert {proposal.signal.signal_type for proposal in run.proposals} == {
        "regulatory_change",
        "microlearning_opportunity",
    }
    assert run.coverage_gaps == []


def test_review_store_persists_and_decides_proposals(tmp_path) -> None:
    source = SourceDefinition(
        id="free-source",
        name="Free Source",
        url="https://example.gov/source",
        source_type=SourceType.OFFICIAL_REGULATOR,
        authority="official",
        jurisdictions=["US"],
        topics=["safety training"],
    )
    snapshot = SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title="Final rule updates required training",
        text="Covered employers must train workers by July 1, 2027.",
    )
    proposal = RegWatchAdapter().evaluate(source, snapshot)[0]
    store = SourceReviewStore(tmp_path / "reviews.jsonl")

    store.save_many([proposal])
    saved = store.list()

    assert len(saved) == 1
    assert saved[0].id == proposal.id
    assert saved[0].approval_state == "needs_review"
    assert saved[0].source_hash == snapshot.content_hash

    decided = store.decide(proposal.id, state="approved_for_brief")

    assert decided.approval_state == "approved_for_brief"
    assert store.list()[0].approval_state == "approved_for_brief"
