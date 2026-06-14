"""MCP parity tests for enterprise remediation tools."""

from __future__ import annotations

import pytest

from complyos.api.mcp_server import (
    approve_ai_proposal,
    approve_privacy_request,
    check_readiness,
    collect_governance_packet,
    collect_security_evidence,
    configure_privacy_retention,
    create_legal_hold,
    create_privacy_request,
    decide_import_row,
    list_evidence_ledger,
    preview_import_batch,
    promote_import_batch,
    propose_field_mapping,
    run_privacy_retention,
)

CSV_TEXT = "user_id,course_id,status,source_record_id\nu1,c1,completed,sr1\n"


@pytest.fixture(autouse=True)
def _elevated_mcp_role(monkeypatch):
    """These tests exercise privileged tool functionality, not authz.

    The MCP surface now defaults to a least-privileged proposal-only role, so
    opt these flows up to owner. The least-privilege default (and that it blocks
    privileged operations) is covered by tests/unit/test_mcp_authz.py.
    """
    monkeypatch.setenv("COMPLYOS_MCP_ROLE", "owner")


async def test_mcp_readiness_and_import_flow(tmp_path) -> None:
    db_path = str(tmp_path / "mcp.db")

    readiness = await check_readiness(db_path=db_path)
    assert "readiness-only" in readiness["posture"]

    preview = await preview_import_batch(csv_text=CSV_TEXT, db_path=db_path)
    assert preview["can_promote"] is True

    promoted = await promote_import_batch(batch_id=preview["batch_id"], db_path=db_path)
    assert promoted["status"] == "PROMOTED"

    evidence = await list_evidence_ledger(db_path=db_path)
    assert evidence["items"][0]["query_type"] == "import.promote"


async def test_mcp_evidence_listing_is_tenant_scoped(tmp_path) -> None:
    db_path = str(tmp_path / "mcp-evidence-tenant.db")
    from complyos.core.repository import LocalRepository

    repo = LocalRepository(db_path)
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

    evidence = await list_evidence_ledger(db_path=db_path, tenant_id="tenant-a")

    assert {item["output_hash"] for item in evidence["items"]} == {"tenant-a-hash"}


async def test_mcp_import_decision_flow(tmp_path) -> None:
    db_path = str(tmp_path / "mcp-decision.db")
    preview = await preview_import_batch(
        csv_text="user_id,course_id,status,extra\nu1,c1,completed,note\n",
        db_path=db_path,
    )
    row_id = preview["rows_preview"][0].get("id")
    assert row_id is None

    from complyos.core.repository import LocalRepository

    stored_row = LocalRepository(db_path).list_import_rows(preview["batch_id"])[0]
    decision = await decide_import_row(
        batch_id=preview["batch_id"],
        row_id=stored_row["id"],
        decision_type="accept",
        db_path=db_path,
    )

    assert decision["row_status"] == "VALID"


async def test_mcp_ai_proposal_is_metadata_only(tmp_path) -> None:
    db_path = str(tmp_path / "mcp-ai.db")

    proposal = await propose_field_mapping(["User ID", "Course ID"], db_path=db_path)
    approved = await approve_ai_proposal(proposal_id=proposal["proposal_id"], db_path=db_path)

    assert proposal["output"]["state_mutation_allowed"] is False
    assert approved["status"] == "APPROVED"


async def test_mcp_security_evidence_packet(tmp_path) -> None:
    db_path = str(tmp_path / "mcp-security.db")

    packet = await collect_security_evidence(period="2026-Q2", db_path=db_path)

    assert packet["posture"] == "readiness_only"
    assert any(control["control_id"] == "CC7.3" for control in packet["controls"])


async def test_mcp_governance_packet(tmp_path) -> None:
    db_path = str(tmp_path / "mcp-governance.db")

    packet = await collect_governance_packet(lane="campus", db_path=db_path)

    assert packet["posture"] == "readiness_only"
    assert any(
        area["area_id"] == "fcra-employment-decision-boundary"
        for area in packet["areas"]
    )


async def test_mcp_privacy_admin_surfaces(tmp_path) -> None:
    db_path = str(tmp_path / "mcp-privacy.db")

    request = await create_privacy_request(
        subject_id="u-privacy",
        request_type="access",
        region="US-CA",
        db_path=db_path,
    )
    assert request["subject_id"] == "u-privacy"
    assert request["status"] == "PENDING_CONTROLLER_APPROVAL"

    approved = await approve_privacy_request(
        request_id=request["request_id"],
        approval_note="controller approved",
        db_path=db_path,
    )
    assert approved["status"] == "APPROVED"

    retention = await configure_privacy_retention(
        raw_import_days=30,
        evidence_days=2555,
        action_log_days=2555,
        ai_proposal_days=180,
        privacy_request_days=365,
        db_path=db_path,
    )
    assert retention["policy"]["action_log_days"] == 2555

    retention_run = await run_privacy_retention(dry_run=True, db_path=db_path)
    assert retention_run["dry_run"] is True

    hold = await create_legal_hold(
        subject_id="u-privacy",
        scope="subject",
        reason="investigation",
        db_path=db_path,
    )
    assert hold["status"] == "ACTIVE"
