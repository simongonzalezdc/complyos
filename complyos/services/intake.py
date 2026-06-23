"""Training intake: capture -> proposal-only draft packet -> human-confirmed scope.

Intake is the LearningOps Suite's front door for training requests. A
coordinator or business requester says *what they want*; ComplyOS captures it,
drafts a packet that flags missing information and *suggests* a priority and
routing destination, and then waits for an accountable human to confirm scope
before any work is treated as agreed.

This service is the **tracer-bullet** for the repeatable "suite-module" shape
(see ``docs/suite-module-pattern.md``). Every later suite module should follow
the same five beats:

1. **Capture** — a tenant-scoped, ``require_permission``-gated write of a typed
   request in a non-committal state (here ``create_request`` -> ``DRAFT``).
2. **Draft packet (proposal-only)** — a deterministic, PII-light draft that
   restates the request, flags gaps, and proposes next steps. It carries
   ``confirms_scope=False`` / ``requires_human_confirmation=True`` and NEVER
   changes state (here ``draft_packet`` -> :class:`IntakePacket`).
3. **Human-approval / confirm gate** — a single elevated-permission step that is
   the only path to the committed state, stamping who approved and when (here
   ``confirm_scope`` -> ``CONFIRMED``). The proposal-only/agent role can draft +
   read but is denied this step.
4. **Action log** — every capture, draft, and confirm writes an action-log
   entry for the evidence trail.
5. **Surfaces + tests** — the same service is reachable from CLI, API v1, and
   MCP with cross-surface parity, and the maturity label flips to **Live** only
   once it is implemented and tested.

Authz split (mirrors attestations): drafting + reading is gated at
``intake:submit`` (which the proposal-only ``agent_service_account`` role holds);
confirming scope is gated at ``intake:confirm`` (which that role deliberately
lacks). AI/agents can propose; only an elevated human confirms scope.

Claim boundary: an intake request — even a confirmed one — records scope intent
and human approval to *start work*. It never asserts anyone is "certified" or
"compliant".
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    IntakePacket,
    IntakePriority,
    IntakeStatus,
    TrainingRequest,
)
from complyos.services.context import (
    PERM_INTAKE_CONFIRM,
    PERM_INTAKE_SUBMIT,
    ActorContext,
    require_permission,
)

# Required fields a complete intake request should carry. The draft packet flags
# any of these that are absent (deterministic missing-info detection).
_REQUIRED_FIELDS: tuple[str, ...] = (
    "audience",
    "business_context",
    "constraints",
    "requested_by_date",
)

# Deterministic keyword -> routing destination map. Matched against the request's
# free text (title + business context). First match wins; otherwise the request
# routes to general instructional design. This is a transparent baseline, not a
# model: the routing is a *suggestion* the human owner can override at confirm.
# Each rule is (matching keywords, destination, rationale).
_ROUTING_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("compliance", "regulation", "regulatory", "policy", "audit", "mandatory"),
        "compliance-training",
        "regulatory/compliance language present",
    ),
    (
        ("onboard", "new hire", "orientation"),
        "onboarding",
        "onboarding language present",
    ),
    (
        ("system", "tool", "software", "platform", "rollout", "migration"),
        "systems-enablement",
        "systems/tooling language present",
    ),
    (
        ("leadership", "manager", "management", "coaching"),
        "leadership-development",
        "leadership language present",
    ),
)

_DEFAULT_ROUTING = "instructional-design"
_DEFAULT_ROUTING_RATIONALE = "no specialized routing keyword matched; default queue"


class IntakeService:
    """Authorization-gated training-intake capture, drafting, and scope confirmation."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    # ------------------------------------------------------------------
    # 1. Capture
    # ------------------------------------------------------------------
    def create_request(
        self,
        context: ActorContext,
        *,
        requester: str,
        title: str,
        audience: str | None = None,
        priority: IntakePriority | str | None = None,
        business_context: str | None = None,
        constraints: str | None = None,
        requested_by_date: date | None = None,
    ) -> TrainingRequest:
        """Capture a training request as a typed ``TrainingRequest`` in ``DRAFT``.

        Gated at ``intake:submit`` (the proposal-only/agent role holds this).
        Capturing a request is explicitly NOT agreeing to do the work — the
        status is ``DRAFT`` and scope is unconfirmed until ``confirm_scope``.
        """
        require_permission(context, PERM_INTAKE_SUBMIT)

        title = title.strip()
        if not title:
            raise ValueError("title is required to capture an intake request")
        requester = requester.strip()
        if not requester:
            raise ValueError("requester is required to capture an intake request")

        resolved_priority = self._coerce_priority(priority)
        request = TrainingRequest(
            id=str(uuid4()),
            tenant_id=context.tenant_id,
            requester=requester,
            title=title,
            audience=_clean(audience),
            priority=resolved_priority,
            business_context=_clean(business_context),
            constraints=_clean(constraints),
            requested_by_date=requested_by_date,
            status=IntakeStatus.DRAFT,
            created_by=context.actor_id,
            created_at=datetime.now(UTC),
        )
        self.repository.save_intake_request(request)
        self._log(
            context,
            action="intake.request.create",
            object_id=request.id,
            metadata={"title": title, "status": request.status.value},
        )
        return request

    # ------------------------------------------------------------------
    # 2. Draft packet (proposal-only)
    # ------------------------------------------------------------------
    def draft_packet(
        self,
        context: ActorContext,
        *,
        request_id: str,
    ) -> IntakePacket:
        """Draft a proposal-only intake packet for a captured request.

        Gated at ``intake:submit``. The packet flags **missing info**, proposes a
        priority, and proposes a routing destination — deterministically. It
        carries ``confirms_scope=False`` and ``requires_human_confirmation=True``
        and writes NO state change: drafting can never confirm scope. The human
        owner uses it to decide whether to ``confirm_scope``.
        """
        require_permission(context, PERM_INTAKE_SUBMIT)
        request = self._require_request(context, request_id)

        missing_info = self._missing_info(request)
        suggested_priority = request.priority or self._suggest_priority(request)
        routing, rationale = self._suggest_routing(request)

        packet = IntakePacket(
            request_id=request.id,
            tenant_id=request.tenant_id,
            title=request.title,
            requester=request.requester,
            audience=request.audience,
            business_context=request.business_context,
            constraints=request.constraints,
            requested_by_date=request.requested_by_date,
            missing_info=missing_info,
            suggested_priority=suggested_priority,
            suggested_routing=routing,
            routing_rationale=rationale,
            confirms_scope=False,
            requires_human_confirmation=True,
            drafted_by_provider="deterministic",
        )
        self._log(
            context,
            action="intake.packet.draft",
            object_id=request.id,
            metadata={
                "missing_info_count": len(missing_info),
                "suggested_priority": suggested_priority.value,
                "suggested_routing": routing,
                "confirms_scope": False,
            },
        )
        return packet

    # ------------------------------------------------------------------
    # 3. Human-approval / confirm gate (the guardrail)
    # ------------------------------------------------------------------
    def confirm_scope(
        self,
        context: ActorContext,
        *,
        request_id: str,
        note: str | None = None,
    ) -> TrainingRequest:
        """Confirm scope: the explicit human step that moves DRAFT -> CONFIRMED.

        Gated at ``intake:confirm`` — an ELEVATED permission the proposal-only
        ``agent_service_account`` role deliberately lacks. This is the only path
        that marks scope confirmed; it stamps ``confirmed_by``/``confirmed_at`` so
        the approval is attributable. A request already withdrawn or confirmed
        cannot be re-confirmed.
        """
        require_permission(context, PERM_INTAKE_CONFIRM)
        request = self._require_request(context, request_id)

        if request.status is IntakeStatus.CONFIRMED:
            raise ValueError(f"intake request already confirmed: {request_id}")
        if request.status is IntakeStatus.WITHDRAWN:
            raise ValueError(f"withdrawn intake request cannot be confirmed: {request_id}")

        confirmed_at = datetime.now(UTC)
        clean_note = _clean(note)
        self.repository.confirm_intake_request(
            request_id,
            confirmed_by=context.actor_id,
            confirmed_at=confirmed_at,
            confirmation_note=clean_note,
        )
        self._log(
            context,
            action="intake.scope.confirm",
            object_id=request_id,
            metadata={"confirmed_by": context.actor_id, "note": clean_note},
        )
        confirmed = self.repository.get_intake_request(request_id)
        assert confirmed is not None  # just written
        return confirmed

    # ------------------------------------------------------------------
    # 4. Read
    # ------------------------------------------------------------------
    def list_requests(
        self,
        context: ActorContext,
        *,
        status: IntakeStatus | str | None = None,
    ) -> list[TrainingRequest]:
        """List the tenant's intake requests (``intake:submit``), optionally by status.

        Tenant-scoped at the repository: only requests owned by the caller's
        tenant are returned, so one tenant can never read another's intake queue.
        """
        require_permission(context, PERM_INTAKE_SUBMIT)
        resolved_status = self._coerce_status(status) if status is not None else None
        return self.repository.list_intake_requests(
            tenant_id=context.tenant_id, status=resolved_status
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _require_request(
        self, context: ActorContext, request_id: str
    ) -> TrainingRequest:
        """Load a request and refuse cross-tenant access (ownership, not permission)."""
        request = self.repository.get_intake_request(request_id)
        if request is None:
            raise ValueError(f"unknown intake request: {request_id}")
        if request.tenant_id != context.tenant_id:
            raise PermissionError("cannot act on an intake request owned by another tenant")
        return request

    @staticmethod
    def _missing_info(request: TrainingRequest) -> list[str]:
        """Deterministically flag which required fields the request is missing."""
        return [field for field in _REQUIRED_FIELDS if getattr(request, field) in (None, "")]

    @staticmethod
    def _suggest_priority(request: TrainingRequest) -> IntakePriority:
        """Suggest a priority from the requested-by date (proposal-only).

        Deterministic baseline: a near-term requested-by date raises priority; an
        undated request defaults to MEDIUM (it cannot be urgent until it is
        understood). The human owner can override this at scope confirmation.
        """
        due = request.requested_by_date
        if due is not None:
            days_out = (due - datetime.now(UTC).date()).days
            if days_out <= 7:
                return IntakePriority.URGENT
            if days_out <= 30:
                return IntakePriority.HIGH
        return IntakePriority.MEDIUM

    @staticmethod
    def _suggest_routing(request: TrainingRequest) -> tuple[str, str]:
        """Suggest a routing destination from request text (proposal-only).

        Transparent keyword match over title + business context. Returns the
        destination and a short rationale; the human owner can re-route at
        confirm time. Never a model dependency — a deterministic baseline.
        """
        haystack = " ".join(
            part.lower()
            for part in (request.title, request.business_context)
            if part
        )
        for keywords, destination, rationale in _ROUTING_RULES:
            if any(keyword in haystack for keyword in keywords):
                return destination, rationale
        return _DEFAULT_ROUTING, _DEFAULT_ROUTING_RATIONALE

    @staticmethod
    def _coerce_priority(
        priority: IntakePriority | str | None,
    ) -> IntakePriority | None:
        if priority is None or isinstance(priority, IntakePriority):
            return priority
        try:
            return IntakePriority(priority)
        except ValueError as exc:
            valid = ", ".join(sorted(IntakePriority.values()))
            raise ValueError(
                f"unknown intake priority {priority!r}; expected one of: {valid}"
            ) from exc

    @staticmethod
    def _coerce_status(status: IntakeStatus | str) -> IntakeStatus:
        if isinstance(status, IntakeStatus):
            return status
        try:
            return IntakeStatus(status)
        except ValueError as exc:
            valid = ", ".join(sorted(IntakeStatus.values()))
            raise ValueError(
                f"unknown intake status {status!r}; expected one of: {valid}"
            ) from exc

    def _log(
        self,
        context: ActorContext,
        *,
        action: str,
        object_id: str,
        metadata: dict[str, object],
    ) -> None:
        self.repository.save_action_log(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            surface=context.surface,
            action=action,
            object_type="intake_request",
            object_id=object_id,
            result="success",
            request_id=context.request_id,
            metadata=metadata,
        )


def _clean(value: str | None) -> str | None:
    """Trim a free-text field; treat blank/whitespace-only as absent (None)."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
