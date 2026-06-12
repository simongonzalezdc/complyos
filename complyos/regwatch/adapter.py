"""RegWatch policy adapter over shared source-intelligence snapshots."""

from __future__ import annotations

import hashlib
import re

from complyos.source_intel.models import (
    SourceDefinition,
    SourceProposal,
    SourceSignal,
    SourceSnapshot,
    SourceType,
)

REGULATORY_KEYWORDS = {
    "must",
    "required",
    "require",
    "shall",
    "effective",
    "final rule",
    "covered employers",
    "compliance",
    "deadline",
}


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _best_quote(text: str, keywords: set[str]) -> str:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in keywords):
            return sentence
    return text.strip()[:240]


def _proposal_id(adapter_name: str, snapshot: SourceSnapshot) -> str:
    digest = hashlib.sha256(f"{adapter_name}:{snapshot.content_hash}".encode()).hexdigest()
    return digest[:16]


class RegWatchAdapter:
    """Create reviewable compliance proposals from authoritative source changes."""

    name = "regwatch"

    def evaluate(
        self,
        source: SourceDefinition,
        snapshot: SourceSnapshot,
    ) -> list[SourceProposal]:
        lowered = f"{snapshot.title} {snapshot.text}".lower()
        matched = sorted(keyword for keyword in REGULATORY_KEYWORDS if keyword in lowered)
        is_authoritative = (
            source.source_type == SourceType.OFFICIAL_REGULATOR or source.authority == "official"
        )

        if not matched or not is_authoritative:
            return []

        score = min(1.0, 0.6 + (0.05 * len(matched)) + 0.15)
        quote = _best_quote(snapshot.text, REGULATORY_KEYWORDS)
        signal = SourceSignal(
            id=f"regwatch-{_proposal_id(self.name, snapshot)}",
            source_id=source.id,
            signal_type="regulatory_change",
            title=snapshot.title,
            summary=f"Possible regulatory obligation detected from {source.name}.",
            score=score,
            topics=source.topics,
            jurisdictions=source.jurisdictions,
            evidence_quote=quote,
            reasons=[
                "authoritative_source",
                *[f"matched:{keyword}" for keyword in matched[:5]],
            ],
        )
        return [
            SourceProposal(
                id=f"proposal-{signal.id}",
                adapter_name=self.name,
                signal=signal,
                source_url=source.url,
                source_hash=snapshot.content_hash,
                evidence_chain=[
                    "source_registry",
                    "source_snapshot",
                    self.name,
                    "human_approval",
                ],
                suggested_action={
                    "action_type": "review_obligation",
                    "review_queue": "regwatch",
                    "requires_legal_or_compliance_owner": True,
                    "next_step": "Map the source change to affected learner groups and controls.",
                },
            )
        ]
