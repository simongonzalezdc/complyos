"""Unit tests for the MCP server tools."""

from __future__ import annotations

from datetime import date

from complyos.api.mcp_server import (
    _get_connector,
    audit_compliance_gaps,
    check_connector_health,
    generate_audit_report,
    get_user_compliance_status,
)
from complyos.connectors.workday import WorkdayConnector


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


class TestConnectorSelection:
    def test_get_connector_defaults_to_mock(self):
        connector = _get_connector()
        assert connector.name == "mock"

    def test_get_connector_selects_workday_with_env(self, monkeypatch):
        monkeypatch.setenv("WORKDAY_BASE_URL", "https://wd2-impl-services1.workday.com/test")
        monkeypatch.setenv("WORKDAY_USERNAME", "test_user")
        monkeypatch.setenv("WORKDAY_PASSWORD", "test_pass")
        connector = _get_connector()
        assert isinstance(connector, WorkdayConnector)


class TestRulesMCPTools:
    async def test_validate_assignment_rule(self, monkeypatch, tmp_path):
        from complyos.api.mcp_server import validate_assignment_rule

        # Seed a local repo
        from complyos.core.repository import LocalRepository
        from complyos.models.domain import Course, User

        db = str(tmp_path / "mcp_rules.db")
        repo = LocalRepository(db)
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Engineering",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_course(Course(id="c1", code="SEC-101", title="Security"))

        monkeypatch.setattr("complyos.api.mcp_server.LocalRepository", lambda: LocalRepository(db))

        result = await validate_assignment_rule(
            name="Eng Security",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            deadline_days=30,
        )
        assert result["valid"] is True
        assert result["issues"] == []

    async def test_preview_assignment_rule(self, monkeypatch, tmp_path):
        from complyos.api.mcp_server import preview_assignment_rule
        from complyos.core.repository import LocalRepository
        from complyos.models.domain import Course, User

        db = str(tmp_path / "mcp_preview.db")
        repo = LocalRepository(db)
        repo.save_user(
            User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Engineering",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            )
        )
        repo.save_course(Course(id="c1", code="SEC-101", title="Security"))

        monkeypatch.setattr("complyos.api.mcp_server.LocalRepository", lambda: LocalRepository(db))

        result = await preview_assignment_rule(
            name="Eng Security",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            deadline_days=30,
        )
        assert result["rule_name"] == "Eng Security"
        assert len(result["users"]) == 1
        assert result["total_missing_enrollments"] == 1


class TestRemediationMCPTool:
    async def test_remediate_compliance_gaps(self):
        from complyos.api.mcp_server import remediate_compliance_gaps

        result = await remediate_compliance_gaps()
        assert result["gaps_found"] >= 2
        assert result["actions_taken"] >= 2
        assert len(result["actions"]) == result["actions_taken"]
        assert len(result["evidence_hash"]) == 64

    async def test_remediate_with_no_actions(self):
        from complyos.api.mcp_server import remediate_compliance_gaps

        result = await remediate_compliance_gaps(
            department="Nonexistent", auto_remind=False
        )
        assert result["gaps_found"] == 0
        assert result["actions_taken"] == 0


class TestExportMCPTool:
    async def test_export_audit_report_html(self, tmp_path):
        from complyos.api.mcp_server import export_audit_report_html

        output = str(tmp_path / "report.html")
        result = await export_audit_report_html(output_path=output)
        assert result["output_path"] == output
        assert result["gaps_found"] >= 2
        assert len(result["evidence_hash"]) == 64
