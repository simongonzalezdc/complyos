"""Readiness service tests."""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.readiness import ReadinessService


def test_readiness_is_explicitly_readiness_only(tmp_path) -> None:
    service = ReadinessService(LocalRepository(str(tmp_path / "ready.db")))
    context = default_local_context(surface="cli")

    report = service.check(context)

    assert "readiness-only" in report.posture
    assert report.summary
    assert any(control.id == "gated-import-lifecycle" for control in report.controls)
    assert "SOC 2 certified" in report.forbidden_claims
