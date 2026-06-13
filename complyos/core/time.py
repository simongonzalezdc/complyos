"""Time helpers for ComplyOS persistence and audit timestamps."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC timestamp using the project's existing DB shape.

    SQLite-backed SQLAlchemy ``DateTime`` columns in this project currently round-trip
    naive ``datetime`` values. We still source the value from an aware UTC clock to
    avoid deprecated naive UTC APIs while preserving storage compatibility.
    """

    return datetime.now(UTC).replace(tzinfo=None)
