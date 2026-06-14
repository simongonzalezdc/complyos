"""Audit service-wrapper authorization and shape-parity tests (WP10).

The service layer is the single authorization choke-point for the audit /
report / status / digest flow. Each method must enforce its permission and fail
closed for an under-privileged context, while returning the same shapes the
routes returned before the wrapper existed.
"""

from __future__ import annotations

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.audit_views import shape_gaps, shape_report
from complyos.core.repository import LocalRepository
from complyos.services.audit import AuditService
from complyos.services.context import AuthorizationError, default_local_context


def _service(tmp_path) -> AuditService:
    return AuditService(MockConnector(), LocalRepository(str(tmp_path / "audit.db")))


async def test_run_audit_requires_audit_run_and_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)
    # read_only has audit:read but NOT audit:run.
    context = default_local_context(surface="api", role="read_only")

    with pytest.raises(AuthorizationError) as exc:
        await service.run_audit(context)

    assert exc.value.permission == "audit:run"


async def test_run_audit_for_owner_returns_gap_shape(tmp_path) -> None:
    service = _service(tmp_path)
    context = default_local_context(surface="api", role="owner")

    gaps, ledger = await service.run_audit(context)
    shaped = shape_gaps(gaps, ledger)

    assert "gaps_found" in shaped
    assert shaped["evidence_hash"] == ledger.output_hash


async def test_generate_report_requires_audit_run_and_returns_report_shape(tmp_path) -> None:
    service = _service(tmp_path)
    denied = default_local_context(surface="api", role="read_only")
    with pytest.raises(AuthorizationError):
        await service.generate_report(denied)

    owner = default_local_context(surface="api", role="owner")
    report = await service.generate_report(owner)
    shaped = shape_report(report)
    assert "gaps_by_severity" in shaped


async def test_get_status_requires_audit_read_and_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)
    # importer has neither audit:read nor audit:run.
    context = default_local_context(surface="api", role="importer")

    with pytest.raises(AuthorizationError) as exc:
        await service.get_status(context, user_id="u1")

    assert exc.value.permission == "audit:read"


async def test_get_status_for_read_only_returns_status_dict(tmp_path) -> None:
    service = _service(tmp_path)
    context = default_local_context(surface="api", role="read_only")

    result = await service.get_status(context, user_id="u1")

    assert isinstance(result, dict)
    assert result["summary"]["total_mandatory"] >= 1


async def test_get_digest_requires_audit_read_and_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)
    context = default_local_context(surface="api", role="importer")

    with pytest.raises(AuthorizationError) as exc:
        await service.get_digest(context)

    assert exc.value.permission == "audit:read"


async def test_get_digest_for_read_only_returns_digest_shape(tmp_path) -> None:
    service = _service(tmp_path)
    context = default_local_context(surface="api", role="read_only")

    digest = await service.get_digest(context)
    payload = digest.model_dump(mode="json")

    assert payload["trend"] == "baseline"
    assert "evidence_hash" in payload
    assert "snapshot_id" in payload
