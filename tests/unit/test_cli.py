"""Tests for the ComplyOS CLI."""

from __future__ import annotations

import json

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
