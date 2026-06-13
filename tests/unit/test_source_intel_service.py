from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.microlearning import MicrolearningAdapter
from complyos.regwatch import RegWatchAdapter
from complyos.services.context import AuthorizationError, default_local_context
from complyos.services.source_intel import SourceIntelService
from complyos.source_intel import SourceDefinition, SourceIntelEngine, SourceSnapshot, SourceType
from complyos.source_intel.monitor import SourceMonitorRun


def _run_with_two_proposals() -> SourceMonitorRun:
    source = SourceDefinition(
        id="official-source",
        name="Official Source",
        url="https://example.gov/rule",
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
    proposals = SourceIntelEngine(adapters=[RegWatchAdapter(), MicrolearningAdapter()]).evaluate(
        [source], [snapshot]
    )
    return SourceMonitorRun(
        source_count=1,
        snapshot_count=1,
        proposal_count=len(proposals),
        proposals=proposals,
        coverage_gaps=[],
    )


def test_source_intel_service_persists_review_queue_with_tenant_scope(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "source-intel.db"))
    service = SourceIntelService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")

    receipt = service.record_run(context, query="training", run=_run_with_two_proposals())
    proposals = service.list_proposals(context)

    assert receipt["proposal_count"] == 2
    assert {proposal["tenant_id"] for proposal in proposals} == {"tenant-a"}
    assert {proposal["approval_state"] for proposal in proposals} == {"needs_review"}
    assert {proposal["signal_type"] for proposal in proposals} == {
        "regulatory_change",
        "microlearning_opportunity",
    }

    other_context = default_local_context(tenant_id="tenant-b", role="compliance_manager")
    assert service.list_proposals(other_context) == []


def test_source_intel_service_validates_review_state_and_permission(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "source-intel-auth.db"))
    service = SourceIntelService(repo)
    manager = default_local_context(tenant_id="tenant-a", role="compliance_manager")
    service.record_run(manager, query="training", run=_run_with_two_proposals())
    proposal_id = service.list_proposals(manager)[0]["id"]

    decided = service.decide_proposal(
        manager,
        proposal_id=proposal_id,
        state="approved_for_brief",
    )
    assert decided["approval_state"] == "approved_for_brief"
    assert decided["decided_by"] == manager.actor_id

    with pytest.raises(ValueError, match="invalid source-intelligence review state"):
        service.decide_proposal(manager, proposal_id=proposal_id, state="auto_publish")

    read_only = default_local_context(tenant_id="tenant-a", role="read_only")
    with pytest.raises(AuthorizationError):
        service.decide_proposal(read_only, proposal_id=proposal_id, state="rejected")


def test_source_intel_service_schedules_executions_and_exports_review_packet(
    tmp_path,
) -> None:
    repo = LocalRepository(str(tmp_path / "source-intel-hardening.db"))
    service = SourceIntelService(repo)
    context = default_local_context(tenant_id="tenant-a", role="compliance_manager")
    now = datetime(2026, 6, 12, 12, 0, 0)

    schedule = service.create_schedule(
        context,
        name="daily-training-watch",
        query="training",
        interval_hours=24,
        source_ids=["fixture-official-training-source"],
        mode="fixture",
    )

    assert schedule["name"] == "daily-training-watch"
    assert schedule["status"] == "active"
    assert service.due_schedules(context, now=now)[0]["id"] == schedule["id"]

    receipt = service.record_run(context, query="training", run=_run_with_two_proposals())
    execution = service.record_schedule_execution(
        context,
        schedule_id=schedule["id"],
        run_id=receipt["run_id"],
        status="succeeded",
        started_at=now,
        finished_at=now,
        summary={"proposal_count": receipt["proposal_count"]},
    )

    assert execution["status"] == "succeeded"
    assert execution["run_id"] == receipt["run_id"]
    assert service.due_schedules(context, now=now) == []
    assert service.due_schedules(context, now=now + timedelta(hours=25))[0]["id"] == schedule["id"]

    proposal_id = service.list_proposals(context)[0]["id"]
    service.decide_proposal(context, proposal_id=proposal_id, state="approved_for_brief")

    packet = service.export_review_packet(context)

    assert packet["tenant_id"] == "tenant-a"
    assert packet["proposal_count"] == 2
    assert packet["decided_count"] == 1
    assert packet["schedules"][0]["name"] == "daily-training-watch"
    assert packet["job_executions"][0]["status"] == "succeeded"
    assert packet["proposals"][0]["run_id"] == receipt["run_id"]
