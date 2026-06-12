"""Service-layer actor context and permission tests."""

from __future__ import annotations

import pytest

from complyos.services.context import (
    PERM_IMPORT_PROMOTE,
    AuthorizationError,
    default_local_context,
    require_permission,
)


def test_owner_local_context_has_all_permissions() -> None:
    context = default_local_context(surface="cli", role="owner")

    require_permission(context, PERM_IMPORT_PROMOTE)
    assert context.tenant_id == "local-default"
    assert context.surface == "cli"


def test_read_only_context_fails_closed_for_mutation() -> None:
    context = default_local_context(surface="api", role="read_only")

    with pytest.raises(AuthorizationError) as exc:
        require_permission(context, PERM_IMPORT_PROMOTE)

    assert exc.value.permission == PERM_IMPORT_PROMOTE
    assert exc.value.code == "permission_denied"
