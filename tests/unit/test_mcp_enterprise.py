"""MCP parity tests for enterprise remediation tools."""

from __future__ import annotations

from complyos.api.mcp_server import (
    approve_ai_proposal,
    check_readiness,
    decide_import_row,
    list_evidence_ledger,
    preview_import_batch,
    promote_import_batch,
    propose_field_mapping,
)

CSV_TEXT = "user_id,course_id,status,source_record_id\nu1,c1,completed,sr1\n"


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
