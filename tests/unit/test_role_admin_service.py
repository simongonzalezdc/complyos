"""Tests for the tenant-scoped role-binding admin service."""

from __future__ import annotations

import pytest

from complyos.core.repository import LocalRepository
from complyos.services.context import AuthorizationError, default_local_context
from complyos.services.role_admin import RoleAdminService


def _repo(tmp_path, name: str) -> LocalRepository:
    return LocalRepository(str(tmp_path / name))


def test_role_admin_requires_admin_manage(tmp_path) -> None:
    service = RoleAdminService(_repo(tmp_path, "roles-authz.db"))
    # admin role intentionally lacks admin:manage (only owner has it).
    context = default_local_context(surface="api", role="admin", tenant_id="tenant-a")

    with pytest.raises(AuthorizationError) as exc:
        service.set_role_binding(context, actor_id="actor-1", role="reviewer")

    assert exc.value.permission == "admin:manage"

    with pytest.raises(AuthorizationError):
        service.list_role_bindings(context)

    with pytest.raises(AuthorizationError):
        service.remove_role_binding(context, actor_id="actor-1")


def test_role_admin_set_list_remove_roundtrip(tmp_path) -> None:
    service = RoleAdminService(_repo(tmp_path, "roles-roundtrip.db"))
    context = default_local_context(surface="api", role="owner", tenant_id="tenant-a")

    saved = service.set_role_binding(context, actor_id="actor-1", role="reviewer")
    assert saved["actor_id"] == "actor-1"
    assert saved["role"] == "reviewer"
    assert saved["tenant_id"] == "tenant-a"

    listed = service.list_role_bindings(context)
    assert {b["actor_id"] for b in listed} == {"actor-1"}

    # set is upsert: same actor, new role replaces the binding.
    updated = service.set_role_binding(context, actor_id="actor-1", role="read_only")
    assert updated["role"] == "read_only"
    assert len(service.list_role_bindings(context)) == 1

    removed = service.remove_role_binding(context, actor_id="actor-1")
    assert removed["removed"] is True
    assert service.list_role_bindings(context) == []


def test_role_admin_rejects_unknown_role_and_permission(tmp_path) -> None:
    service = RoleAdminService(_repo(tmp_path, "roles-validate.db"))
    context = default_local_context(surface="api", role="owner", tenant_id="tenant-a")

    with pytest.raises(ValueError, match="unknown role"):
        service.set_role_binding(context, actor_id="actor-1", role="not-a-role")

    with pytest.raises(ValueError, match="unknown permissions"):
        service.set_role_binding(
            context,
            actor_id="actor-1",
            role="reviewer",
            permissions_override=["audit:read", "not:a:permission"],
        )


def test_role_admin_remove_missing_binding_raises(tmp_path) -> None:
    service = RoleAdminService(_repo(tmp_path, "roles-missing.db"))
    context = default_local_context(surface="api", role="owner", tenant_id="tenant-a")

    with pytest.raises(ValueError, match="no role binding"):
        service.remove_role_binding(context, actor_id="ghost")


def test_role_admin_is_tenant_scoped_bola(tmp_path) -> None:
    """Tenant A must never see or remove tenant B's bindings."""
    service = RoleAdminService(_repo(tmp_path, "roles-bola.db"))
    ctx_a = default_local_context(surface="api", role="owner", tenant_id="tenant-a")
    ctx_b = default_local_context(surface="api", role="owner", tenant_id="tenant-b")

    service.set_role_binding(ctx_a, actor_id="shared-actor", role="reviewer")
    service.set_role_binding(ctx_b, actor_id="shared-actor", role="read_only")

    a_bindings = service.list_role_bindings(ctx_a)
    b_bindings = service.list_role_bindings(ctx_b)
    assert {b["role"] for b in a_bindings} == {"reviewer"}
    assert {b["role"] for b in b_bindings} == {"read_only"}

    # Tenant A removing the same actor_id must not touch tenant B's binding.
    service.remove_role_binding(ctx_a, actor_id="shared-actor")
    assert service.list_role_bindings(ctx_a) == []
    assert len(service.list_role_bindings(ctx_b)) == 1
