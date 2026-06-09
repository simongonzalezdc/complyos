"""Assignment rules engine for validating and previewing compliance rules."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from complyos.core.repository import LocalRepository
from complyos.models.domain import AssignmentRule, User


class RuleValidationError(Exception):
    """Raised when a rule fails validation."""

    pass


class AssignmentRuleEngine:
    """Evaluate assignment rules against local repository data."""

    def __init__(self, repository: LocalRepository) -> None:
        self.repository = repository

    def validate_rule(self, rule: AssignmentRule) -> dict[str, Any]:
        """Validate a rule for common issues before deployment.

        Returns a dict with 'valid' bool and 'issues' list.
        """
        issues: list[str] = []

        if not rule.active:
            issues.append("Rule is inactive")

        if not rule.course_ids:
            issues.append("No courses specified")
        else:
            missing_courses = []
            for course_id in rule.course_ids:
                if self.repository.get_course(course_id) is None:
                    missing_courses.append(course_id)
            if missing_courses:
                issues.append(f"Unknown course IDs: {missing_courses}")

        if not rule.target_criteria:
            issues.append("No target criteria specified (would affect all users)")

        if rule.deadline_days_from_trigger <= 0:
            issues.append("Deadline must be > 0 days")

        # Check if any users match
        affected = self.preview_rule(rule)
        if not affected["users"]:
            issues.append("No users match the target criteria")

        return {"valid": len(issues) == 0, "issues": issues, "preview": affected}

    def preview_rule(self, rule: AssignmentRule) -> dict[str, Any]:
        """Preview which users would be affected by a rule without assigning.

        Returns affected users and their missing courses.
        """
        if not rule.active:
            return {"users": [], "total_missing_enrollments": 0}

        users = self._matching_users(rule)
        course_map = {
            c.id: c
            for c in self.repository.list_courses()
            if c.id in rule.course_ids
        }

        results = []
        total_missing = 0

        for user in users:
            enrollments = self.repository.list_enrollments(user_id=user.id)
            enrolled_course_ids = {e.course_id for e in enrollments}
            missing = [
                course_map[cid]
                for cid in rule.course_ids
                if cid not in enrolled_course_ids and cid in course_map
            ]
            if missing:
                total_missing += len(missing)
                results.append(
                    {
                        "user": user,
                        "missing_courses": missing,
                        "deadline": date.today() + timedelta(days=rule.deadline_days_from_trigger),
                    }
                )

        return {
            "users": results,
            "total_missing_enrollments": total_missing,
            "rule_name": rule.name,
        }

    def _matching_users(self, rule: AssignmentRule) -> list[User]:
        """Return users matching the rule's target criteria, minus exceptions."""
        criteria = rule.target_criteria
        users = self.repository.list_users(
            department=criteria.get("department"),
            region=criteria.get("region"),
            employment_status=criteria.get("employment_status"),
        )

        # Apply additional field filters
        for key, value in criteria.items():
            if key not in ("department", "region", "employment_status"):
                users = [u for u in users if u.custom_attributes.get(key) == value]

        # Apply exceptions
        for exc in rule.exceptions:
            exc_key = exc.get("field")
            exc_value = exc.get("value")
            if exc_key and exc_value is not None:
                users = [
                    u
                    for u in users
                    if getattr(u, exc_key, u.custom_attributes.get(exc_key)) != exc_value
                ]

        return users
