"""Tests for the AssignmentRuleEngine."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import (
    AssignmentRule,
    Course,
    EmploymentStatus,
    Enrollment,
    EnrollmentStatus,
    User,
)


@pytest.fixture
def repo(tmp_path):
    return LocalRepository(str(tmp_path / "rules.db"))


@pytest.fixture
def engine(repo: LocalRepository):
    return AssignmentRuleEngine(repo)


@pytest.fixture
def seeded_repo(repo: LocalRepository):
    """Seed repository with users, courses, and enrollments."""
    repo.save_user(
        User(
            id="u1",
            employee_id="E001",
            email="alice@example.com",
            first_name="Alice",
            last_name="Smith",
            department="Engineering",
            region="US",
            hire_date=date(2023, 1, 1),
            employment_status=EmploymentStatus.ACTIVE,
        )
    )
    repo.save_user(
        User(
            id="u2",
            employee_id="E002",
            email="bob@example.com",
            first_name="Bob",
            last_name="Jones",
            department="Engineering",
            region="EU",
            hire_date=date(2023, 1, 1),
            employment_status=EmploymentStatus.ACTIVE,
        )
    )
    repo.save_user(
        User(
            id="u3",
            employee_id="E003",
            email="carol@example.com",
            first_name="Carol",
            last_name="White",
            department="HR",
            region="US",
            hire_date=date(2023, 1, 1),
            employment_status=EmploymentStatus.ACTIVE,
        )
    )
    repo.save_course(Course(id="c1", code="SEC-101", title="Security", mandatory=True))
    repo.save_course(Course(id="c2", code="LEAD-101", title="Leadership", mandatory=False))
    return repo


class TestValidateRule:
    def test_valid_rule(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="Engineering Security",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            deadline_days_from_trigger=30,
        )
        result = engine.validate_rule(rule)
        assert result["valid"] is True
        assert result["issues"] == []
        assert len(result["preview"]["users"]) == 2

    def test_inactive_rule(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="Inactive",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            active=False,
        )
        result = engine.validate_rule(rule)
        assert result["valid"] is False
        assert any("inactive" in i.lower() for i in result["issues"])

    def test_missing_courses(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="Bad Courses",
            target_criteria={"department": "Engineering"},
            course_ids=["c99"],
        )
        result = engine.validate_rule(rule)
        assert result["valid"] is False
        assert any("Unknown course" in i for i in result["issues"])

    def test_no_target_criteria(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="Too Broad",
            target_criteria={},
            course_ids=["c1"],
        )
        result = engine.validate_rule(rule)
        assert result["valid"] is False
        assert any("target criteria" in i.lower() for i in result["issues"])

    def test_no_courses(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="No Courses",
            target_criteria={"department": "Engineering"},
            course_ids=[],
        )
        result = engine.validate_rule(rule)
        assert result["valid"] is False
        assert any("No courses" in i for i in result["issues"])

    def test_bad_deadline(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="Bad Deadline",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            deadline_days_from_trigger=0,
        )
        result = engine.validate_rule(rule)
        assert result["valid"] is False
        assert any("Deadline" in i for i in result["issues"])

    def test_no_matching_users(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="No Match",
            target_criteria={"department": "Sales"},
            course_ids=["c1"],
        )
        result = engine.validate_rule(rule)
        assert result["valid"] is False
        assert any("No users match" in i for i in result["issues"])


class TestPreviewRule:
    def test_shows_missing_courses(
        self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine
    ):
        rule = AssignmentRule(
            name="Eng Security",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            deadline_days_from_trigger=30,
        )
        result = engine.preview_rule(rule)
        assert result["rule_name"] == "Eng Security"
        assert len(result["users"]) == 2
        assert result["total_missing_enrollments"] == 2
        # Check deadline is computed
        expected_deadline = date.today() + timedelta(days=30)
        assert result["users"][0]["deadline"] == expected_deadline

    def test_respects_exceptions(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        # Give u1 an enrollment so only u2 is missing
        seeded_repo.save_enrollment(
            Enrollment(
                id="e1",
                user_id="u1",
                course_id="c1",
                status=EnrollmentStatus.COMPLETED,
            )
        )
        rule = AssignmentRule(
            name="Eng Security",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            exceptions=[{"field": "id", "value": "u2"}],
        )
        result = engine.preview_rule(rule)
        # u1 has completed, u2 is excluded by exception
        assert len(result["users"]) == 0
        assert result["total_missing_enrollments"] == 0

    def test_inactive_rule_returns_empty(
        self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine
    ):
        rule = AssignmentRule(
            name="Inactive",
            target_criteria={"department": "Engineering"},
            course_ids=["c1"],
            active=False,
        )
        result = engine.preview_rule(rule)
        assert result["users"] == []
        assert result["total_missing_enrollments"] == 0

    def test_filters_by_region(self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine):
        rule = AssignmentRule(
            name="US Only",
            target_criteria={"region": "US"},
            course_ids=["c1"],
        )
        result = engine.preview_rule(rule)
        assert len(result["users"]) == 2  # u1 (Eng/US) and u3 (HR/US)

    def test_custom_attribute_filter(
        self, seeded_repo: LocalRepository, engine: AssignmentRuleEngine
    ):
        # u1 has a custom attribute
        user = seeded_repo.get_user("u1")
        assert user is not None
        user.custom_attributes["level"] = "senior"
        seeded_repo.save_user(user)

        rule = AssignmentRule(
            name="Senior Only",
            target_criteria={"level": "senior"},
            course_ids=["c1"],
        )
        result = engine.preview_rule(rule)
        assert len(result["users"]) == 1
        assert result["users"][0]["user"].id == "u1"
