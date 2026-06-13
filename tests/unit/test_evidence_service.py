"""Evidence service-wrapper authorization and shape-parity tests (WP10).

EvidenceService is the single authorization choke-point for exporting audit
reports (evidence:export) and reading the evidence ledger (evidence:read).
"""

from __future__ import annotations

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.repository import LocalRepository
from complyos.services.context import AuthorizationError, default_local_context
from complyos.services.evidence import EvidenceService


def _service(tmp_path) -> EvidenceService:
    return EvidenceService(MockConnector(), LocalRepository(str(tmp_path / "evidence.db")))


async def test_export_report_requires_evidence_export_and_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)
    # read_only has evidence:read but NOT evidence:export.
    context = default_local_context(surface="api", role="read_only")

    with pytest.raises(AuthorizationError) as exc:
        await service.export_report(context, output_path=str(tmp_path / "r.html"))

    assert exc.value.permission == "evidence:export"


async def test_export_report_for_reviewer_writes_html_and_returns_summary(tmp_path) -> None:
    service = _service(tmp_path)
    # reviewer has evidence:export.
    context = default_local_context(surface="api", role="reviewer")
    output_path = str(tmp_path / "report.html")

    result = await service.export_report(context, output_path=output_path)

    assert result["output_path"] == output_path
    assert "gaps_found" in result
    assert "total_users" in result
    assert "evidence_hash" in result


def test_list_ledger_requires_evidence_read_and_fails_closed(tmp_path) -> None:
    service = _service(tmp_path)
    # An empty-permission context fails closed on the read gate.
    context = default_local_context(surface="api", role="owner").model_copy(
        update={"permissions": ()}
    )

    with pytest.raises(AuthorizationError) as exc:
        service.list_ledger(context)

    assert exc.value.permission == "evidence:read"


def test_list_ledger_is_tenant_scoped(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "ledger.db"))
    repo.append_evidence_entry(
        tenant_id="tenant-a",
        query_type="audit",
        query_params={"tenant_id": "tenant-a"},
        raw_data_hash="raw-a",
        transformation_steps=["hash"],
        output_hash="tenant-a-hash",
        output_summary="tenant a evidence",
    )
    repo.append_evidence_entry(
        tenant_id="tenant-b",
        query_type="audit",
        query_params={"tenant_id": "tenant-b"},
        raw_data_hash="raw-b",
        transformation_steps=["hash"],
        output_hash="tenant-b-hash",
        output_summary="tenant b evidence",
    )
    service = EvidenceService(MockConnector(), repo)
    context = default_local_context(surface="api", tenant_id="tenant-a", role="reviewer")

    items = service.list_ledger(context)

    assert {item["output_hash"] for item in items} == {"tenant-a-hash"}
