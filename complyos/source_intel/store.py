"""Local JSONL review queue for source-intelligence proposals."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from complyos.source_intel.models import SourceProposal


class SourceReviewStore:
    """Persist proposal review state without requiring a paid database service."""

    def __init__(self, path: str | Path = "source-intel-reviews.jsonl") -> None:
        self.path = Path(path)

    def save_many(self, proposals: list[SourceProposal]) -> None:
        existing = {proposal.id: proposal for proposal in self.list()}
        for proposal in proposals:
            existing[proposal.id] = proposal
        self._write(list(existing.values()))

    def list(self) -> list[SourceProposal]:
        if not self.path.exists():
            return []
        proposals = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                proposals.append(SourceProposal.model_validate_json(line))
        return proposals

    def decide(self, proposal_id: str, *, state: str) -> SourceProposal:
        proposals = self.list()
        for proposal in proposals:
            if proposal.id == proposal_id:
                proposal.approval_state = state
                self._write(proposals)
                return proposal
        raise ValueError(f"unknown source-intelligence proposal: {proposal_id}")

    def _write(self, proposals: Sequence[SourceProposal]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = "\n".join(proposal.model_dump_json() for proposal in proposals)
        self.path.write_text(f"{payload}\n" if payload else "", encoding="utf-8")
