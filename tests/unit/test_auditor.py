"""Unit tests for the compliance auditor."""

from __future__ import annotations

import pytest

from complyos.connectors.csv_file import CSVConnector
from complyos.connectors.mock import MockConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.models.domain import AssignmentRule


@pytest.fixture
def mock_connector() -> MockConnector:
    return MockConnector()


@pytest.fixture
def auditor(mock_connector: MockConnector) -> ComplianceAuditor:
    return ComplianceAuditor(mock_connector)


class TestAuditGaps:
    async def test_finds_active_users_with_missing_mandatory(self, auditor: ComplianceAuditor):
        gaps, ledger = await auditor.audit_gaps()

        # u3 (Carol) is missing both mandatory courses
        # u4 (David) is missing security and respect is not started overdue
        # u5 (Eve) is terminated and should NOT appear
        assert len(gaps) >= 2

        user_ids = {g.user.id for g in gaps}
        assert "u3" in user_ids  # Carol missing everything
        assert "u4" in user_ids  # David missing security, respect not started
        assert "u5" not in user_ids  # Eve terminated, excluded

        assert ledger.query_type == "audit_gaps"
        assert len(ledger.output_hash) == 64  # SHA-256
        assert "Found" in ledger.output_summary

    async def test_filters_by_department(self, auditor: ComplianceAuditor):
        gaps, _ = await auditor.audit_gaps(department="Engineering")

        # Only Alice and Bob are Engineering; Carol and David are HR
        for g in gaps:
            assert g.user.department == "Engineering"

    async def test_filters_by_region(self, auditor: ComplianceAuditor):
        gaps, _ = await auditor.audit_gaps(region="MX")

        # Only David is in MX
        assert len(gaps) >= 1
        assert all(g.user.region == "MX" for g in gaps)

    async def test_calculates_severity_correctly(self, auditor: ComplianceAuditor):
        gaps, _ = await auditor.audit_gaps()

        for g in gaps:
            if g.days_overdue and g.days_overdue > 60:
                assert g.severity == "critical"
            elif g.days_overdue and g.days_overdue > 30:
                assert g.severity == "high"
            elif g.days_overdue and g.days_overdue > 7:
                assert g.severity == "medium"

    async def test_respects_assignment_rules(self, auditor: ComplianceAuditor):
        rules = [
            AssignmentRule(
                name="Engineering Only",
                course_ids=["c1"],
                target_criteria={"department": "Engineering"},
            )
        ]
        gaps, _ = await auditor.audit_gaps(rules=rules)

        for g in gaps:
            assert g.user.department == "Engineering"
            assert g.rule_name == "Engineering Only"


class TestGetUserStatus:
    async def test_returns_complete_status(self, auditor: ComplianceAuditor):
        result = await auditor.get_user_status("u1")

        assert "error" not in result
        assert result["user"]["id"] == "u1"
        assert result["summary"]["total_mandatory"] == 2  # 2 mandatory courses in mock
        assert result["summary"]["completed"] == 1  # Alice completed respect
        assert result["summary"]["missing"] == 1  # Missing security

    async def test_returns_error_for_missing_user(self, auditor: ComplianceAuditor):
        result = await auditor.get_user_status("nonexistent")
        assert "error" in result


class TestGenerateReport:
    async def test_generates_structured_report(self, auditor: ComplianceAuditor):
        report = await auditor.generate_report()

        assert report.gaps_found >= 2
        assert len(report.evidence_hash) == 64
        assert report.generated_at is not None
        assert "all" in report.scope
        assert sum(report.gaps_by_severity.values()) == report.gaps_found

    async def test_department_scoped_report(self, auditor: ComplianceAuditor):
        report = await auditor.generate_report(department="HR")

        assert report.scope == "department=HR, region=None"
        for dept, _count in report.gaps_by_department.items():
            assert dept == "HR"


class TestSeverityCalculation:
    def test_no_mandatory_is_low(self, auditor: ComplianceAuditor):
        from complyos.models.domain import Course
        course = Course(id="c1", code="OPT-101", title="Optional", mandatory=False)
        assert auditor._calculate_severity([course], None) == "low"

    def test_no_overdue_is_medium(self, auditor: ComplianceAuditor):
        from complyos.models.domain import Course
        course = Course(id="c1", code="REQ-101", title="Required", mandatory=True)
        assert auditor._calculate_severity([course], None) == "medium"

    def test_overdue_60_plus_is_critical(self, auditor: ComplianceAuditor):
        from complyos.models.domain import Course
        course = Course(id="c1", code="REQ-101", title="Required", mandatory=True)
        assert auditor._calculate_severity([course], 61) == "critical"

    def test_overdue_30_plus_is_high(self, auditor: ComplianceAuditor):
        from complyos.models.domain import Course
        course = Course(id="c1", code="REQ-101", title="Required", mandatory=True)
        assert auditor._calculate_severity([course], 31) == "high"

    def test_overdue_7_plus_is_medium(self, auditor: ComplianceAuditor):
        from complyos.models.domain import Course
        course = Course(id="c1", code="REQ-101", title="Required", mandatory=True)
        assert auditor._calculate_severity([course], 8) == "medium"

    def test_overdue_under_7_is_low(self, auditor: ComplianceAuditor):
        from complyos.models.domain import Course
        course = Course(id="c1", code="REQ-101", title="Required", mandatory=True)
        assert auditor._calculate_severity([course], 3) == "low"


class TestCSVExpiryAudit:
    async def test_csv_completed_but_expired_mandatory_course_is_gap(self, tmp_path):
        (tmp_path / "users.csv").write_text(
            "id,email,first_name,last_name,department,region,hire_date,employment_status\n"
            "u1,alice@example.com,Alice,Smith,Engineering,US,2024-01-01,active\n"
        )
        (tmp_path / "courses.csv").write_text(
            "id,code,title,mandatory\n"
            "c1,SEC-101,Security Basics,true\n"
        )
        (tmp_path / "enrollments.csv").write_text(
            "id,user_id,course_id,status,completed_date,expires_at,completion_percentage\n"
            "e1,u1,c1,completed,1999-01-01,2000-01-01,100\n"
        )

        auditor = ComplianceAuditor(CSVConnector(tmp_path))
        gaps, _ledger = await auditor.audit_gaps()

        assert len(gaps) == 1
        assert gaps[0].user.id == "u1"
        assert [course.id for course in gaps[0].missing_courses] == ["c1"]
