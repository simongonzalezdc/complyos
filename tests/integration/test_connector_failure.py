"""Connector-failure integration test: sync fails closed, preserving prior data.

Plan §6.5 / §13.3: a connector that raises mid-sync must NOT destroy the prior
local cache. ``AuditService.sync`` fetches all connector data BEFORE it calls
``clear_all()``, so a fetch failure propagates before any local data is cleared —
the previous audit-relevant records remain intact.
"""

from __future__ import annotations

from typing import Any

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.repository import LocalRepository
from complyos.services.audit import AuditService
from complyos.services.context import default_local_context


class _MidSyncFailureConnector(MockConnector):
    """Authenticates and lists users, then fails while fetching courses."""

    name = "failing-mock"

    async def get_courses(self, filters: dict[str, Any] | None = None) -> list:
        raise ConnectionError("simulated LMS outage mid-sync")


async def test_connector_failure_mid_sync_preserves_prior_records(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "sync-fail.db"))
    context = default_local_context(surface="cli", role="owner")

    # 1. A healthy sync seeds the local cache.
    healthy = await AuditService(MockConnector(), repo).sync(context)
    assert healthy["learning_records"] >= 1
    before = repo.list_learning_records()
    assert before, "healthy sync should have populated learning records"

    # 2. A sync whose connector fails mid-fetch must raise...
    with pytest.raises(ConnectionError):
        await AuditService(_MidSyncFailureConnector(), repo).sync(context)

    # 3. ...and must NOT have cleared the prior cache (fail closed).
    after = repo.list_learning_records()
    assert len(after) == len(before)
