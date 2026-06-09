"""Tests for the ComplyOS CLI."""

from __future__ import annotations

import json
from datetime import date

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


class TestAuditCommand:
    def test_audit_default_output(self):
        result = runner.invoke(app, ["audit"])
        assert result.exit_code == 0
        assert "Gaps found:" in result.output
        assert "Users affected:" in result.output
        assert "Evidence hash:" in result.output

    def test_audit_json_output(self):
        result = runner.invoke(app, ["audit", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "gaps_found" in data
        assert "users_affected" in data
        assert "evidence_hash" in data
        assert "gaps" in data

    def test_audit_filtered_by_department(self):
        result = runner.invoke(app, ["audit", "--department", "Engineering"])
        assert result.exit_code == 0
        assert "Gaps found:" in result.output

    def test_audit_json_skips_table(self):
        result = runner.invoke(app, ["audit", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "gaps" in data
        # Table headers should not appear in JSON output
        assert "User" not in result.output


class TestReportCommand:
    def test_report_default_output(self):
        result = runner.invoke(app, ["report"])
        assert result.exit_code == 0
        assert "Generated:" in result.output
        assert "Gaps found:" in result.output
        assert "Evidence hash:" in result.output

    def test_report_json_output(self):
        result = runner.invoke(app, ["report", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "generated_at" in data
        assert "gaps_found" in data
        assert "gaps_by_severity" in data

    def test_report_json_skips_tables(self):
        result = runner.invoke(app, ["report", "--json"])
        assert result.exit_code == 0
        # Table headers should not appear in JSON output
        assert "Severity" not in result.output


class TestStatusCommand:
    def test_status_existing_user(self):
        result = runner.invoke(app, ["status", "u1"])
        assert result.exit_code == 0
        assert "Alice Smith" in result.output
        assert "Compliance:" in result.output

    def test_status_missing_user(self):
        result = runner.invoke(app, ["status", "nonexistent"])
        assert result.exit_code == 1
        assert "Error:" in result.output

    def test_status_json_output(self):
        result = runner.invoke(app, ["status", "u1", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "user" in data
        assert "summary" in data
        assert "courses" in data

    def test_status_json_skips_table(self):
        result = runner.invoke(app, ["status", "u1", "--json"])
        assert result.exit_code == 0
        # Table headers should not appear in JSON output
        assert "Course Status" not in result.output


class TestHealthCommand:
    def test_health_output(self):
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        assert "Connector:" in result.output
        assert "Authenticated:" in result.output
        assert "Status:" in result.output


class TestMCPCommand:
    def test_mcp_runs_server(self, monkeypatch):
        called = False

        def fake_main():
            nonlocal called
            called = True

        monkeypatch.setattr("complyos.api.mcp_server.main", fake_main)
        result = runner.invoke(app, ["mcp"])
        assert result.exit_code == 0
        assert called


class TestRulesCommands:
    def test_validate_rule_valid(self, tmp_path):
        rule_file = tmp_path / "rule.json"
        rule_file.write_text(
            json.dumps(
                {
                    "name": "Test Rule",
                    "target_criteria": {"department": "Engineering"},
                    "course_ids": ["c1"],
                    "deadline_days_from_trigger": 30,
                }
            )
        )
        result = runner.invoke(app, ["validate-rule", str(rule_file)])
        assert result.exit_code == 0
        assert "Rule is valid" in result.output or "Rule has issues" in result.output

    def test_preview_rule(self, tmp_path):
        rule_file = tmp_path / "rule.json"
        rule_file.write_text(
            json.dumps(
                {
                    "name": "Preview Rule",
                    "target_criteria": {"department": "Engineering"},
                    "course_ids": ["c1"],
                    "deadline_days_from_trigger": 30,
                }
            )
        )
        result = runner.invoke(app, ["preview-rule", str(rule_file)])
        assert result.exit_code == 0
        assert "Rule:" in result.output


class TestRemediateCommand:
    def test_remediate_default(self):
        result = runner.invoke(app, ["remediate"])
        assert result.exit_code == 0
        assert "Gaps found:" in result.output
        assert "Actions taken:" in result.output
        assert "Evidence hash:" in result.output

    def test_remediate_no_remind(self):
        result = runner.invoke(app, ["remediate", "--no-remind"])
        assert result.exit_code == 0
        assert "Gaps found:" in result.output


class TestSyncCommand:
    def test_sync_success(self, monkeypatch, tmp_path):
        class FakeConnector:
            name = "fake"

            async def authenticate(self):
                return True

            async def get_users(self):
                from complyos.models.domain import User
                return [
                    User(
                        id="u1",
                        employee_id="E001",
                        email="a@example.com",
                        first_name="A",
                        last_name="A",
                        department="Eng",
                        region="US",
                        hire_date=date(2023, 1, 1),
                        employment_status="active",
                    )
                ]

            async def get_courses(self):
                from complyos.models.domain import Course
                return [Course(id="c1", code="SEC-101", title="Security")]

            async def get_enrollments(self):
                return []

        monkeypatch.setattr("complyos.cli._get_connector", lambda: FakeConnector())
        db_path = str(tmp_path / "sync.db")
        result = runner.invoke(app, ["sync", "--db", db_path])
        assert result.exit_code == 0
        assert "Synced 1 users, 1 courses, 0 enrollments" in result.output

    def test_sync_auth_failure(self, monkeypatch):
        class BadConnector:
            name = "bad"

            async def authenticate(self):
                return False

        monkeypatch.setattr("complyos.cli._get_connector", lambda: BadConnector())
        result = runner.invoke(app, ["sync", "--db", ":memory:"])
        assert result.exit_code == 1
        assert "authentication failed" in result.output
