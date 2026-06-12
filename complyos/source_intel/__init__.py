"""Shared source-intelligence primitives for RegWatch and Microlearning Radar."""

from complyos.source_intel.engine import SourceIntelAdapter, SourceIntelEngine
from complyos.source_intel.models import (
    SourceDefinition,
    SourceProposal,
    SourceSignal,
    SourceSnapshot,
    SourceType,
    build_snapshot,
)

__all__ = [
    "SourceDefinition",
    "SourceIntelAdapter",
    "SourceIntelEngine",
    "SourceProposal",
    "SourceSignal",
    "SourceSnapshot",
    "SourceType",
    "build_snapshot",
]
