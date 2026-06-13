"""Pydantic models for source intake, crawl snapshots, signals, and proposals."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(StrEnum):
    OFFICIAL_REGULATOR = "official_regulator"
    PROFESSIONAL_BODY = "professional_body"
    VENDOR_DOCS = "vendor_docs"
    INTERNAL_UPLOAD = "internal_upload"
    NEWS_OR_WEB = "news_or_web"


class SourceDefinition(BaseModel):
    """A source registry entry shared by RegWatch and Microlearning Radar."""

    id: str
    name: str
    url: str
    source_type: SourceType
    authority: str
    jurisdictions: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceSnapshot(BaseModel):
    """One fetched/uploaded source body at a point in time."""

    source_id: str
    url: str
    title: str
    text: str
    content_hash: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_text(
        cls,
        *,
        source_id: str,
        url: str,
        title: str,
        text: str,
        fetched_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SourceSnapshot:
        normalized_text = " ".join(text.split())
        content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
        return cls(
            source_id=source_id,
            url=url,
            title=title,
            text=text,
            content_hash=content_hash,
            fetched_at=fetched_at or datetime.now().astimezone(),
            metadata=metadata or {},
        )


class SourceSignal(BaseModel):
    """A scored finding extracted from a source snapshot."""

    id: str
    source_id: str
    signal_type: str
    title: str
    summary: str
    score: float
    topics: list[str] = Field(default_factory=list)
    jurisdictions: list[str] = Field(default_factory=list)
    evidence_quote: str
    reasons: list[str] = Field(default_factory=list)


class SourceProposal(BaseModel):
    """Human-review proposal generated from a source signal."""

    id: str
    adapter_name: str
    signal: SourceSignal
    source_url: str
    source_hash: str
    approval_state: str = "needs_review"
    evidence_chain: list[str]
    suggested_action: dict[str, Any]
    generated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


def build_snapshot(
    source: SourceDefinition,
    *,
    title: str,
    text: str,
    fetched_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> SourceSnapshot:
    """Create a deterministic content-hash snapshot for a registered source."""
    return SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title=title,
        text=text,
        fetched_at=fetched_at,
        metadata=metadata,
    )
