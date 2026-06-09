"""Tests for the HTML report exporter."""

from __future__ import annotations

from datetime import date, datetime

from complyos.core.report_exporter import export_html
from complyos.models.domain import AuditReport, ComplianceGap, Course, User


class TestExportHTML:
    def test_exports_html_file(self, tmp_path):
        report = AuditReport(
            generated_at=datetime(2024, 6, 1, 12, 0, 0),
            scope="all",
            total_users_audited=10,
            gaps_found=2,
            gaps_by_severity={"critical": 1, "high": 0, "medium": 1, "low": 0},
            gaps_by_department={"Engineering": 2},
            top_missing_courses=[("Security", 2)],
            evidence_hash="abc123",
            details=[
                ComplianceGap(
                    user=User(
                        id="u1",
                        employee_id="E001",
                        email="a@example.com",
                        first_name="Alice",
                        last_name="Smith",
                        department="Engineering",
                        region="US",
                        hire_date=date(2023, 1, 1),
                        employment_status="active",
                    ),
                    missing_courses=[Course(id="c1", code="SEC-101", title="Security")],
                    severity="critical",
                    days_overdue=14,
                )
            ],
        )
        output = tmp_path / "report.html"
        result = export_html(report, str(output))
        assert result == str(output)
        assert output.exists()
        content = output.read_text()
        assert "ComplyOS Audit Report" in content
        assert "Alice Smith" in content
        assert "Security" in content
        assert "critical" in content
        assert "abc123" in content
        assert "14" in content

    def test_empty_report(self, tmp_path):
        report = AuditReport(
            generated_at=datetime(2024, 6, 1, 12, 0, 0),
            scope="all",
            total_users_audited=10,
            gaps_found=0,
            gaps_by_severity={},
            gaps_by_department={},
            top_missing_courses=[],
            evidence_hash="def456",
            details=[],
        )
        output = tmp_path / "empty.html"
        export_html(report, str(output))
        content = output.read_text()
        assert "No gaps found" in content
        assert "def456" in content
