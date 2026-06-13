"""PolicyRuleService authorization and shape-parity tests (WP11).

PolicyRuleService is the single authorization choke-point for validating
(rules:preview) and previewing (rules:preview) assignment rules. Both fail
closed for an under-privileged context and return the same shapes the
AssignmentRuleEngine produced for the CLI/MCP surfaces.
"""

from __future__ import annotations

from datetime import date

import pytest

from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import (
    AssignmentRule,
    Course,
    EmploymentStatus,
    User,
)
from complyos.services.context import AuthorizationError, default_local_context
from complyos.services.policy_rules import PolicyRuleService


def _seeded_repo(tmp_path) -> LocalRepository:
    repo = LocalRepository(str(tmp_path / "rules.db"))
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
    repo.save_course(Course(id="c1", code="SEC-101", title="Security", mandatory=True))
    return repo


def _rule() -> AssignmentRule:
    return AssignmentRule(
        name="Engineering Security",
        target_criteria={"department": "Engineering"},
        course_ids=["c1"],
        deadline_days_from_trigger=30,
    )


def test_validate_requires_rules_preview_and_fails_closed(tmp_path) -> None:
    service = PolicyRuleService(_seeded_repo(tmp_path))
    # importer lacks rules:preview.
    context = default_local_context(surface="api", role="importer")

    with pytest.raises(AuthorizationError) as exc:
        service.validate(context, _rule())

    assert exc.value.permission == "rules:preview"


def test_validate_for_authorized_context_matches_engine(tmp_path) -> None:
    repo = _seeded_repo(tmp_path)
    service = PolicyRuleService(repo)
    context = default_local_context(surface="cli", role="compliance_manager")

    result = service.validate(context, _rule())
    expected = AssignmentRuleEngine(repo).validate_rule(_rule())

    assert result == expected
    assert result["valid"] is True


def test_preview_requires_rules_preview_and_fails_closed(tmp_path) -> None:
    service = PolicyRuleService(_seeded_repo(tmp_path))
    context = default_local_context(surface="api", role="importer")

    with pytest.raises(AuthorizationError) as exc:
        service.preview(context, _rule())

    assert exc.value.permission == "rules:preview"


def test_preview_for_authorized_context_matches_engine(tmp_path) -> None:
    repo = _seeded_repo(tmp_path)
    service = PolicyRuleService(repo)
    context = default_local_context(surface="mcp", role="agent_service_account")

    result = service.preview(context, _rule())
    expected = AssignmentRuleEngine(repo).preview_rule(_rule())

    assert result == expected
    assert result["rule_name"] == "Engineering Security"
    assert len(result["users"]) == 1
