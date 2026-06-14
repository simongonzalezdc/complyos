"""Service-layer role-binding administration (/admin/roles).

RBAC assignments were previously not manageable through any surface — roles were
read-only catalog data. This service is the single authorization choke-point for
creating, listing, and removing per-actor role bindings: every method requires
``admin:manage`` and is tenant-scoped on ``context.tenant_id`` so an admin in
tenant A can never see or mutate a binding owned by tenant B (BOLA-safe).
"""

from __future__ import annotations

from typing import Any

from complyos.core.repository import LocalRepository
from complyos.services.context import (
    ALL_PERMISSIONS,
    PERM_ADMIN_MANAGE,
    ROLE_PERMISSIONS,
    ActorContext,
    require_permission,
)


class RoleAdminService:
    """Authorization-gated, tenant-scoped role-binding management."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def list_role_bindings(
        self,
        context: ActorContext,
        *,
        actor_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List role bindings for the current tenant (admin:manage)."""
        require_permission(context, PERM_ADMIN_MANAGE)
        return self.repository.list_role_bindings(
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            limit=limit,
        )

    def set_role_binding(
        self,
        context: ActorContext,
        *,
        actor_id: str,
        role: str,
        permissions_override: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create or replace a tenant-scoped role binding (admin:manage)."""
        require_permission(context, PERM_ADMIN_MANAGE)
        if role not in ROLE_PERMISSIONS:
            raise ValueError(f"unknown role: {role}")
        if permissions_override is not None:
            unknown = sorted(set(permissions_override) - ALL_PERMISSIONS)
            if unknown:
                raise ValueError(f"unknown permissions: {', '.join(unknown)}")
        binding = self.repository.set_role_binding(
            tenant_id=context.tenant_id,
            actor_id=actor_id,
            role=role,
            permissions_override=permissions_override,
            created_by=context.actor_id,
        )
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="admin.role_binding.set",
            object_type="role_binding",
            object_id=actor_id,
            result="saved",
            request_id=context.request_id,
            metadata={"role": role, "has_override": permissions_override is not None},
        )
        return binding

    def remove_role_binding(self, context: ActorContext, *, actor_id: str) -> dict[str, Any]:
        """Remove a tenant-scoped role binding (admin:manage)."""
        require_permission(context, PERM_ADMIN_MANAGE)
        removed = self.repository.remove_role_binding(
            tenant_id=context.tenant_id,
            actor_id=actor_id,
        )
        if not removed:
            raise ValueError(f"no role binding for actor: {actor_id}")
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action="admin.role_binding.remove",
            object_type="role_binding",
            object_id=actor_id,
            result="removed",
            request_id=context.request_id,
        )
        return {"actor_id": actor_id, "removed": True}
