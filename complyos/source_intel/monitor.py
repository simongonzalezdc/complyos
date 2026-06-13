"""Source monitoring orchestration over source clients and adapters."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from complyos.source_intel.clients import SourceFetchReport
from complyos.source_intel.engine import SourceIntelEngine
from complyos.source_intel.models import SourceDefinition, SourceProposal


class SourceClient(Protocol):
    """A source client that can fetch snapshots for one source."""

    def fetch(self, source: SourceDefinition, *, query: str) -> SourceFetchReport:
        """Fetch source snapshots for a query."""


class SourceMonitorRun(BaseModel):
    """Summary of one source-monitoring run."""

    source_count: int
    snapshot_count: int
    proposal_count: int
    proposals: list[SourceProposal] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)


class SourceMonitor:
    """Run source clients and fan snapshots into source-intelligence adapters."""

    def __init__(
        self,
        *,
        sources: list[SourceDefinition],
        clients: dict[str, SourceClient],
        engine: SourceIntelEngine,
    ) -> None:
        self.sources = sources
        self.clients = clients
        self.engine = engine

    def run(self, *, query: str) -> SourceMonitorRun:
        snapshots = []
        coverage_gaps = []
        for source in self.sources:
            client = self.clients.get(source.id)
            if client is None:
                coverage_gaps.append(f"{source.id}: no client configured")
                continue
            try:
                report = client.fetch(source, query=query)
            except Exception as exc:  # noqa: BLE001 - one bad source must not abort the run
                # Degrade gracefully: record the failure as a coverage gap and
                # keep the snapshots already collected from healthy sources.
                coverage_gaps.append(f"{source.id}: fetch failed: {type(exc).__name__}: {exc}")
                continue
            snapshots.extend(report.snapshots)
            coverage_gaps.extend(f"{source.id}: {gap}" for gap in report.coverage_gaps)

        proposals = self.engine.evaluate(self.sources, snapshots)
        return SourceMonitorRun(
            source_count=len(self.sources),
            snapshot_count=len(snapshots),
            proposal_count=len(proposals),
            proposals=proposals,
            coverage_gaps=coverage_gaps,
        )
