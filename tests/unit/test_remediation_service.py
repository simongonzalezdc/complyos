"""Remediation service-wrapper authorization and shape-parity tests (WP10).

RemediationService is the single authorization choke-point for proposing
(dry-run, remediation:propose) and executing (remediation:execute) remediation.
"""

from __future__ import annotations

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.audit_views import shape_remediation
from complyos.services.context import AuthorizationError, default_local_context
from complyos.services.remediation import RemediationService


def _service() -> RemediationService:
    return RemediationService(MockConnector())


async def test_propose_requires_remediation_propose_and_fails_closed() -> None:
    service = _service()
    # read_only has neither remediation permission.
    context = default_local_context(surface="api", role="read_only")

    with pytest.raises(AuthorizationError) as exc:
        await service.propose(context)

    assert exc.value.permission == "remediation:propose"


async def test_propose_for_agent_role_returns_remediation_shape_without_executing() -> None:
    service = _service()
    # agent_service_account can propose but NOT execute.
    context = default_local_context(surface="api", role="agent_service_account")

    gaps, actions, ledger = await service.propose(context)
    shaped = shape_remediation(gaps, actions, ledger)

    assert "gaps_found" in shaped
    assert "actions" in shaped
    assert shaped["evidence_hash"] == ledger.output_hash


async def test_execute_requires_remediation_execute_and_fails_closed() -> None:
    service = _service()
    # agent_service_account can propose but cannot execute mutating remediation.
    context = default_local_context(surface="api", role="agent_service_account")

    with pytest.raises(AuthorizationError) as exc:
        await service.execute(context)

    assert exc.value.permission == "remediation:execute"


async def test_execute_for_owner_returns_remediation_shape() -> None:
    service = _service()
    context = default_local_context(surface="api", role="owner")

    gaps, actions, ledger = await service.execute(context, auto_remind=True)
    shaped = shape_remediation(gaps, actions, ledger)

    assert shaped["gaps_found"] == len(gaps)
    assert shaped["actions_taken"] == len(actions)
    assert shaped["evidence_hash"] == ledger.output_hash
