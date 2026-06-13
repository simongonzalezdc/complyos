"""Shared source-intelligence engine.

The engine is intentionally small: crawl/fetch produces SourceSnapshot objects,
then domain adapters turn those snapshots into reviewable proposals.
"""

from __future__ import annotations

from typing import Protocol

from complyos.source_intel.models import SourceDefinition, SourceProposal, SourceSnapshot


class SourceIntelAdapter(Protocol):
    """Domain policy layer for one source-intelligence product surface."""

    name: str

    def evaluate(
        self,
        source: SourceDefinition,
        snapshot: SourceSnapshot,
    ) -> list[SourceProposal]:
        """Return human-review proposals for a source snapshot."""


class SourceIntelEngine:
    """Fan source snapshots out to RegWatch, Microlearning, and future adapters."""

    def __init__(self, adapters: list[SourceIntelAdapter]):
        self.adapters = adapters

    def evaluate(
        self,
        sources: list[SourceDefinition],
        snapshots: list[SourceSnapshot],
    ) -> list[SourceProposal]:
        source_by_id = {source.id: source for source in sources}
        proposals: list[SourceProposal] = []

        for snapshot in snapshots:
            source = source_by_id.get(snapshot.source_id)
            if source is None:
                continue
            for adapter in self.adapters:
                proposals.extend(adapter.evaluate(source, snapshot))

        return proposals
