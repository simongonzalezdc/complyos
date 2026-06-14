"""Service wrapper for assignment-rule validation and preview.

The CLI `validate-rule`/`preview-rule` commands and the MCP
`validate_assignment_rule`/`preview_assignment_rule` tools used to build an
AssignmentRuleEngine and enforce permissions only at the surface. This service
makes the service layer the single authorization choke-point: both methods
accept an ActorContext and call require_permission(rules:preview) before
touching the engine. Return shapes match the AssignmentRuleEngine output the
surfaces produced before the wrapper existed.
"""

from __future__ import annotations

from typing import Any

from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import AssignmentRule
from complyos.services.context import (
    PERM_RULES_PREVIEW,
    ActorContext,
    require_permission,
)


class PolicyRuleService:
    """Authorization-gated assignment-rule validation and preview."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def validate(self, context: ActorContext, rule: AssignmentRule) -> dict[str, Any]:
        """Validate an assignment rule before deployment (rules:preview)."""
        require_permission(context, PERM_RULES_PREVIEW)
        return AssignmentRuleEngine(self.repository).validate_rule(rule)

    def preview(self, context: ActorContext, rule: AssignmentRule) -> dict[str, Any]:
        """Preview which users an assignment rule would affect (rules:preview)."""
        require_permission(context, PERM_RULES_PREVIEW)
        return AssignmentRuleEngine(self.repository).preview_rule(rule)
