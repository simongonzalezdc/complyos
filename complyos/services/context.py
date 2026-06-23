"""Actor/request context and service-layer authorization.

Every product surface (CLI, MCP, API, web, scheduler) should enter service
methods with an ActorContext. Routes can create the context, but services own
permission enforcement so UI/API/MCP drift cannot bypass controls.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

PERM_AUDIT_READ = "audit:read"
PERM_AUDIT_RUN = "audit:run"
PERM_ANALYTICS_READ = "analytics:read"
PERM_EVIDENCE_READ = "evidence:read"
PERM_EVIDENCE_EXPORT = "evidence:export"
PERM_IMPORT_PREVIEW = "import:preview"
PERM_IMPORT_DECIDE = "import:decide"
PERM_IMPORT_PROMOTE = "import:promote"
PERM_RULES_READ = "rules:read"
PERM_RULES_PREVIEW = "rules:preview"
PERM_RULES_WRITE = "rules:write"
PERM_REMEDIATION_PROPOSE = "remediation:propose"
PERM_REMEDIATION_EXECUTE = "remediation:execute"
PERM_CONNECTORS_READ = "connectors:read"
PERM_CONNECTORS_WRITE = "connectors:write"
PERM_AI_PROPOSE = "ai:propose"
PERM_AI_APPROVE = "ai:approve"
PERM_READINESS_READ = "readiness:read"
PERM_SECURITY_EVIDENCE_READ = "security:evidence:read"
PERM_GOVERNANCE_READ = "governance:read"
PERM_PRIVACY_REQUEST = "privacy:request"
PERM_PRIVACY_APPROVE = "privacy:approve"
PERM_PRIVACY_EXPORT = "privacy:export"
PERM_PRIVACY_DELETE = "privacy:delete"
PERM_PRIVACY_RETENTION_MANAGE = "privacy:retention:manage"
PERM_LEGAL_HOLD_MANAGE = "legal_hold:manage"
PERM_SOURCE_INTEL_READ = "source_intel:read"
PERM_SOURCE_INTEL_RUN = "source_intel:run"
PERM_SOURCE_INTEL_DECIDE = "source_intel:decide"
PERM_NOTIFICATIONS_MANAGE = "notifications:manage"
PERM_ATTESTATION_RECORD = "attestation:record"
PERM_ATTESTATION_READ = "attestation:read"
PERM_INTAKE_SUBMIT = "intake:submit"
PERM_INTAKE_CONFIRM = "intake:confirm"
PERM_ROSTERS_READ = "rosters:read"
PERM_ROSTERS_APPROVE = "rosters:approve"
PERM_ADMIN_MANAGE = "admin:manage"

ALL_PERMISSIONS: frozenset[str] = frozenset(
    {
        PERM_AUDIT_READ,
        PERM_AUDIT_RUN,
        PERM_ANALYTICS_READ,
        PERM_EVIDENCE_READ,
        PERM_EVIDENCE_EXPORT,
        PERM_IMPORT_PREVIEW,
        PERM_IMPORT_DECIDE,
        PERM_IMPORT_PROMOTE,
        PERM_RULES_READ,
        PERM_RULES_PREVIEW,
        PERM_RULES_WRITE,
        PERM_REMEDIATION_PROPOSE,
        PERM_REMEDIATION_EXECUTE,
        PERM_CONNECTORS_READ,
        PERM_CONNECTORS_WRITE,
        PERM_AI_PROPOSE,
        PERM_AI_APPROVE,
        PERM_READINESS_READ,
        PERM_SECURITY_EVIDENCE_READ,
        PERM_GOVERNANCE_READ,
        PERM_PRIVACY_REQUEST,
        PERM_PRIVACY_APPROVE,
        PERM_PRIVACY_EXPORT,
        PERM_PRIVACY_DELETE,
        PERM_PRIVACY_RETENTION_MANAGE,
        PERM_LEGAL_HOLD_MANAGE,
        PERM_SOURCE_INTEL_READ,
        PERM_SOURCE_INTEL_RUN,
        PERM_SOURCE_INTEL_DECIDE,
        PERM_NOTIFICATIONS_MANAGE,
        PERM_ATTESTATION_RECORD,
        PERM_ATTESTATION_READ,
        PERM_INTAKE_SUBMIT,
        PERM_INTAKE_CONFIRM,
        PERM_ROSTERS_READ,
        PERM_ROSTERS_APPROVE,
        PERM_ADMIN_MANAGE,
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "owner": ALL_PERMISSIONS,
    "admin": ALL_PERMISSIONS - {PERM_ADMIN_MANAGE},
    "compliance_manager": frozenset(
        {
            PERM_AUDIT_READ,
            PERM_AUDIT_RUN,
            PERM_ANALYTICS_READ,
            PERM_EVIDENCE_READ,
            PERM_EVIDENCE_EXPORT,
            PERM_RULES_READ,
            PERM_RULES_PREVIEW,
            PERM_RULES_WRITE,
            PERM_REMEDIATION_PROPOSE,
            PERM_REMEDIATION_EXECUTE,
            PERM_CONNECTORS_READ,
            PERM_AI_PROPOSE,
            PERM_AI_APPROVE,
            PERM_READINESS_READ,
            PERM_SECURITY_EVIDENCE_READ,
            PERM_GOVERNANCE_READ,
            PERM_PRIVACY_REQUEST,
            PERM_PRIVACY_APPROVE,
            PERM_PRIVACY_EXPORT,
            PERM_SOURCE_INTEL_READ,
            PERM_SOURCE_INTEL_RUN,
            PERM_SOURCE_INTEL_DECIDE,
            PERM_NOTIFICATIONS_MANAGE,
            PERM_ATTESTATION_RECORD,
            PERM_ATTESTATION_READ,
            PERM_INTAKE_SUBMIT,
            PERM_INTAKE_CONFIRM,
            PERM_ROSTERS_READ,
            PERM_ROSTERS_APPROVE,
        }
    ),
    "privacy_admin": frozenset(
        {
            PERM_EVIDENCE_READ,
            PERM_READINESS_READ,
            PERM_PRIVACY_REQUEST,
            PERM_PRIVACY_APPROVE,
            PERM_PRIVACY_EXPORT,
            PERM_PRIVACY_DELETE,
            PERM_PRIVACY_RETENTION_MANAGE,
            PERM_LEGAL_HOLD_MANAGE,
            PERM_NOTIFICATIONS_MANAGE,
        }
    ),
    "importer": frozenset({PERM_IMPORT_PREVIEW, PERM_IMPORT_DECIDE, PERM_EVIDENCE_READ}),
    "import_approver": frozenset(
        {PERM_IMPORT_PREVIEW, PERM_IMPORT_DECIDE, PERM_IMPORT_PROMOTE, PERM_EVIDENCE_READ}
    ),
    "reviewer": frozenset(
        {
            PERM_AUDIT_READ,
            PERM_ANALYTICS_READ,
            PERM_EVIDENCE_READ,
            PERM_EVIDENCE_EXPORT,
            PERM_READINESS_READ,
            PERM_SECURITY_EVIDENCE_READ,
            PERM_GOVERNANCE_READ,
            PERM_SOURCE_INTEL_READ,
            PERM_ATTESTATION_READ,
        }
    ),
    "agent_service_account": frozenset(
        {
            PERM_AUDIT_READ,
            PERM_AUDIT_RUN,
            PERM_ANALYTICS_READ,
            PERM_EVIDENCE_READ,
            PERM_IMPORT_PREVIEW,
            PERM_RULES_PREVIEW,
            PERM_REMEDIATION_PROPOSE,
            PERM_CONNECTORS_READ,
            PERM_AI_PROPOSE,
            PERM_READINESS_READ,
            PERM_SOURCE_INTEL_READ,
            PERM_SOURCE_INTEL_RUN,
            PERM_ATTESTATION_READ,
            PERM_INTAKE_SUBMIT,
            # NOTE: notifications:manage intentionally withheld. The proposal-only
            # MCP default role must not be able to send arbitrary external email
            # (send_notification) or drain the outbox; raise COMPLYOS_MCP_ROLE for that.
            # NOTE: attestation:record intentionally withheld. An attestation is
            # human-recorded evidence that a person accepted a policy; the AI/agent
            # default role must never be able to mark a learner attested. It may
            # read (attestation:read) so it can report un-attested learners.
            # NOTE: intake:submit IS granted (the agent may draft + read intake
            # requests and packets — the proposal-only side). intake:confirm is
            # intentionally withheld: confirming scope is the human guardrail, so
            # the agent default role can never mark a request scope-confirmed.
            PERM_ROSTERS_READ,
            # NOTE: rosters:read IS granted (the agent may request a snapshot,
            # which only previews/quarantines source data, and read the roster
            # view). rosters:approve is intentionally withheld: approving a
            # snapshot promotes the quarantined import batch into normalized
            # truth, which is the human guardrail. The agent default role can
            # preview but never let an import mutate truth.
        }
    ),
    "read_only": frozenset(
        {
            PERM_AUDIT_READ,
            PERM_ANALYTICS_READ,
            PERM_EVIDENCE_READ,
            PERM_READINESS_READ,
            PERM_SOURCE_INTEL_READ,
            PERM_ATTESTATION_READ,
        }
    ),
}


class AuthorizationError(PermissionError):
    """Raised when a service-layer permission check fails."""

    def __init__(self, permission: str, actor_id: str, surface: str) -> None:
        super().__init__(f"actor '{actor_id}' on {surface} lacks '{permission}'")
        self.permission = permission
        self.actor_id = actor_id
        self.surface = surface
        self.code = "permission_denied"


class ActorContext(BaseModel):
    """Context carried into every service call that touches tenant data."""

    tenant_id: str = "local-default"
    track: str = "workforce"
    actor_id: str = "local-admin"
    actor_type: str = "local_operator"
    role: str = "owner"
    permissions: tuple[str, ...] = Field(default_factory=lambda: tuple(sorted(ALL_PERMISSIONS)))
    surface: str = "cli"
    request_id: str = Field(default_factory=lambda: str(uuid4()))
    auth_method: str = "local_dev"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def has_permission(self, permission: str) -> bool:
        return permission in set(self.permissions)

    def public_dict(self) -> dict[str, str]:
        """Return safe context metadata for logs/API responses."""
        return {
            "tenant_id": self.tenant_id,
            "track": self.track,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "role": self.role,
            "surface": self.surface,
            "request_id": self.request_id,
            "auth_method": self.auth_method,
        }


def permissions_for_role(role: str) -> tuple[str, ...]:
    return tuple(sorted(ROLE_PERMISSIONS.get(role, frozenset())))


def default_local_context(
    *,
    surface: str = "cli",
    track: str = "workforce",
    tenant_id: str = "local-default",
    role: str = "owner",
    actor_id: str | None = None,
    auth_method: str = "local_dev",
) -> ActorContext:
    """Build explicit local/default context for local-first operation."""
    return ActorContext(
        tenant_id=tenant_id,
        track=track,
        actor_id=actor_id or ("local-admin" if role == "owner" else f"local-{role}"),
        actor_type="local_operator" if auth_method == "local_dev" else "service_account",
        role=role,
        permissions=permissions_for_role(role),
        surface=surface,
        auth_method=auth_method,
    )


def require_permission(context: ActorContext, permission: str) -> None:
    """Fail closed unless the actor has the requested permission."""
    if not context.has_permission(permission):
        raise AuthorizationError(permission, context.actor_id, context.surface)
