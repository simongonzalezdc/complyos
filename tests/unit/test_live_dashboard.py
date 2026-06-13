"""Tests for the live dashboard FastAPI app."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from complyos.core.repository import LocalRepository
from complyos.microlearning import MicrolearningAdapter
from complyos.models.domain import AuditReport
from complyos.regwatch import RegWatchAdapter
from complyos.services.context import default_local_context
from complyos.services.source_intel import SourceIntelService
from complyos.source_intel import SourceDefinition, SourceIntelEngine, SourceSnapshot, SourceType
from complyos.source_intel.monitor import SourceMonitorRun
from complyos.web.dashboard import create_dashboard_app


class FakeAuditor:
    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        return AuditReport(
            generated_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
            scope=f"department={department}, region={region}" if department or region else "all",
            total_users_audited=5,
            gaps_found=1,
            gaps_by_severity={"low": 0, "medium": 1, "high": 0, "critical": 0},
            gaps_by_department={"Operations": 1},
            top_missing_courses=[("Safety", 1)],
            evidence_hash="hash-live",
            details=[],
        )


def test_live_dashboard_health() -> None:
    client = TestClient(create_dashboard_app(auditor=FakeAuditor()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "complyos-dashboard"}


def test_live_dashboard_summary_endpoint() -> None:
    client = TestClient(create_dashboard_app(auditor=FakeAuditor()))

    response = client.get("/api/summary?department=Operations")

    assert response.status_code == 200
    assert response.json()["scope"] == "department=Operations, region=None"
    assert response.json()["gaps_found"] == 1
    assert response.json()["evidence_hash"] == "hash-live"


def test_live_dashboard_html_endpoint() -> None:
    client = TestClient(create_dashboard_app(auditor=FakeAuditor()))

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ComplyOS Dashboard" in response.text
    assert "hash-live" in response.text


def test_live_dashboard_source_intel_review_page(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "dashboard-source-intel.db"))
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
    SourceIntelService(repo).record_run(
        default_local_context(role="compliance_manager", surface="dashboard"),
        query="training",
        run=SourceMonitorRun(
            source_count=1,
            snapshot_count=1,
            proposal_count=len(proposals),
            proposals=proposals,
            coverage_gaps=[],
        ),
    )
    client = TestClient(create_dashboard_app(auditor=FakeAuditor(), repository=repo))

    response = client.get("/source-intel/review")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Source Intelligence Review Queue" in response.text
    assert "Final rule and practice guide" in response.text
    assert "needs_review" in response.text
