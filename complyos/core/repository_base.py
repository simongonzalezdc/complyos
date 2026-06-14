"""Shared base for the aggregate repository mixins.

LocalRepository is composed from per-aggregate mixins (privacy, imports,
source-intel, notifications, ...). They all need the same primitives — a
session factory, the owning-tenant resolver — and the legal-hold decision
type. Putting those here lets each mixin inherit them so `self._session(...)`
type-checks, while the concrete repository stays a single composed class.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from complyos.models.database import DBUser, init_db

# Legal-hold scopes that suspend deletion across an entire tenant (not a single
# subject). Both "tenant" and "system" holds must block every retention dataset.
_TENANT_WIDE_HOLD_SCOPES = ("tenant", "system")


@dataclass(frozen=True)
class HoldDecision:
    """Single source of truth for which records an active legal hold protects.

    Centralizing this prevents the per-query drift that let subject- and
    system-scoped holds be silently ignored by most retention-eligibility
    checks (a spoliation risk for a compliance product).
    """

    tenant_blocked: bool
    held_subject_ids: frozenset[str] = field(default_factory=frozenset)

    @property
    def any_active(self) -> bool:
        """True when any active hold exists (tenant/system-wide or per-subject)."""
        return self.tenant_blocked or bool(self.held_subject_ids)


class RepositoryBase:
    """Session factory and shared helpers inherited by every aggregate mixin."""

    def __init__(self, db_path: str = "complyos.db", database_url: str | None = None) -> None:
        self._sessionmaker = init_db(database_url or db_path)

    def _session(self) -> Session:
        return self._sessionmaker()

    @staticmethod
    def _owner_tenant_id(session: Session, user_id: str) -> str:
        """Tenant a learner/item record inherits from its owning user.

        Learning records and enrollments share their learner's tenant so DSR
        export/delete can scope them precisely. Falls back to the default tenant
        only when the learner has not been synced locally (e.g. standalone
        import before an HR sync), matching the column default.
        """
        # no_autoflush: resolving the owner must not flush the half-built record
        # currently pending in the session (its required columns aren't set yet).
        with session.no_autoflush:
            owner = session.get(DBUser, user_id)
        return owner.tenant_id if owner is not None else "local-default"
