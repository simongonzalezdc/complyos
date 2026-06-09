"""Unit tests for the MCP server tools."""

from __future__ import annotations

import pytest

from complyos.api.mcp_server import (
    audit_compliance_gaps,
    check_connector_health,
    generate_audit_report,
    get_user_compliance_status,
)


class TestMCPTools:
    async def test_audit_compliance_gaps(self):
        result = await audit_compliance_gaps()

        assert result["gaps_found"] >= 2
        assert result["users_affected"] >= 2
        assert len(result["evidence_hash"]) == 64
        assert len(result["gaps"]) > 0

        gap = result["gaps"][0]
        assert "user" in gap
        assert "missing_courses" in gap
        assert "severity" in gap

    async def test_audit_compliance_gaps_filtered(self):
        result = await audit_compliance_gaps(department="HR")

        for gap in result["gaps"]:
            assert gap["user"]["department"] == "HR"

    async def test_get_user_compliance_status(self):
        result = await get_user_compliance_status("u1")

        assert "error" not in result
        assert result["user"]["id"] == "u1"
        assert result["summary"]["total_mandatory"] == 2

    async def test_get_user_compliance_status_missing(self):
        result = await get_user_compliance_status("nonexistent")
        assert "error" in result

    async def test_generate_audit_report(self):
        result = await generate_audit_report()

        assert result["gaps_found"] >= 2
        assert len(result["evidence_hash"]) == 64
        assert result["scope"] == "all"
        assert sum(result["gaps_by_severity"].values()) == result["gaps_found"]

    async def test_generate_audit_report_scoped(self):
        result = await generate_audit_report(department="Engineering")

        assert "department=Engineering" in result["scope"]

    async def test_check_connector_health(self):
        result = await check_connector_health()

        assert result["connector"] == "mock"
        assert result["authenticated"] is True
        assert result["status"] == "healthy"
