"""Microlearning policy adapter over shared source-intelligence snapshots."""

from __future__ import annotations

import hashlib
import re

from complyos.source_intel.models import (
    SourceDefinition,
    SourceProposal,
    SourceSignal,
    SourceSnapshot,
)

MICROLEARNING_KEYWORDS = {
    "checklist",
    "examples",
    "feedback",
    "guide",
    "how to",
    "practice",
    "research shows",
    "scenario",
    "skill",
    "training",
}


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _best_quote(text: str) -> str:
    for sentence in _sentences(text):
        lowered = sentence.lower()
        if any(keyword in lowered for keyword in MICROLEARNING_KEYWORDS):
            return sentence
    return text.strip()[:240]


def _proposal_id(adapter_name: str, snapshot: SourceSnapshot) -> str:
    digest = hashlib.sha256(f"{adapter_name}:{snapshot.content_hash}".encode()).hexdigest()
    return digest[:16]


class MicrolearningAdapter:
    """Create reviewable microlearning module proposals from credible sources."""

    name = "microlearning"

    def evaluate(
        self,
        source: SourceDefinition,
        snapshot: SourceSnapshot,
    ) -> list[SourceProposal]:
        lowered = f"{snapshot.title} {snapshot.text} {' '.join(source.topics)}".lower()
        matched = sorted(keyword for keyword in MICROLEARNING_KEYWORDS if keyword in lowered)
        credible = source.authority in {"official", "trusted", "internal"}

        if len(matched) < 2 or not credible:
            return []

        score = min(1.0, 0.45 + (0.06 * len(matched)) + (0.1 if source.topics else 0.0))
        quote = _best_quote(snapshot.text)
        topic = source.topics[0] if source.topics else snapshot.title
        signal = SourceSignal(
            id=f"microlearning-{_proposal_id(self.name, snapshot)}",
            source_id=source.id,
            signal_type="microlearning_opportunity",
            title=snapshot.title,
            summary=f"Teachable source detected for {topic}.",
            score=score,
            topics=source.topics,
            jurisdictions=source.jurisdictions,
            evidence_quote=quote,
            reasons=[*[f"matched:{keyword}" for keyword in matched[:5]], "human_review_required"],
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
                    "action_type": "draft_microlearning_module",
                    "review_queue": "microlearning",
                    "module": {
                        "title": f"Microlearning: {topic.title()}",
                        "duration_minutes": 5,
                        "learning_objectives": [
                            f"Explain the source-backed update for {topic}.",
                            "Apply the guidance in one realistic workplace scenario.",
                        ],
                        "check_for_understanding": [
                            "Which source-backed behavior should the learner apply first?"
                        ],
                    },
                    "next_step": "Instructional designer reviews the proposal before publishing.",
                },
            )
        ]
