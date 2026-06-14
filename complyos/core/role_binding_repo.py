"""Role-binding (RBAC assignment) persistence for LocalRepository.

Every method is tenant-scoped on the indexed ``tenant_id`` column so a caller
in tenant A can never read or mutate a binding owned by tenant B (BOLA-safe).
The service layer owns permission enforcement; this mixin owns persistence.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from complyos.core.repository_base import RepositoryBase
from complyos.core.time import utc_now
from complyos.models.database import DBRoleBinding


class RoleBindingRepositoryMixin(RepositoryBase):
    """CRUD for tenant-scoped role bindings persisted to DBRoleBinding."""

    @staticmethod
    def _to_role_binding_dict(row: DBRoleBinding) -> dict[str, Any]:
        return {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "actor_id": row.actor_id,
            "role": row.role,
            "permissions_override": list(row.permissions_override or []),
            "created_by": row.created_by,
            "created_at": row.created_at,
        }

    def list_role_bindings(
        self,
        *,
        tenant_id: str,
        actor_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List role bindings owned by ``tenant_id`` (optionally one actor)."""
        with self._session() as session:
            query = session.query(DBRoleBinding).where(DBRoleBinding.tenant_id == tenant_id)
            if actor_id:
                query = query.where(DBRoleBinding.actor_id == actor_id)
            rows = query.order_by(DBRoleBinding.created_at.desc()).limit(limit).all()
            return [self._to_role_binding_dict(row) for row in rows]

    def set_role_binding(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        role: str,
        permissions_override: list[str] | None = None,
        created_by: str,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        """Create or replace the role binding for ``actor_id`` within ``tenant_id``."""
        with self._session() as session:
            binding = (
                session.query(DBRoleBinding)
                .where(
                    DBRoleBinding.tenant_id == tenant_id,
                    DBRoleBinding.actor_id == actor_id,
                )
                .first()
            )
            if binding is None:
                binding = DBRoleBinding(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    created_by=created_by,
                    created_at=created_at or utc_now(),
                )
                session.add(binding)
            binding.role = role
            binding.permissions_override = list(permissions_override or [])
            session.commit()
            session.refresh(binding)
            return self._to_role_binding_dict(binding)

    def remove_role_binding(self, *, tenant_id: str, actor_id: str) -> bool:
        """Delete the binding for ``actor_id`` within ``tenant_id``; True if removed."""
        with self._session() as session:
            binding = (
                session.query(DBRoleBinding)
                .where(
                    DBRoleBinding.tenant_id == tenant_id,
                    DBRoleBinding.actor_id == actor_id,
                )
                .first()
            )
            if binding is None:
                return False
            session.delete(binding)
            session.commit()
            return True
