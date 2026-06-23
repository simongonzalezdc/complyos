"""Versioned FastAPI API over ComplyOS application services."""

from __future__ import annotations

import hmac
import os
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from complyos.api.mcp_server import _get_connector, _get_notifier
from complyos.core.audit_views import shape_gaps, shape_remediation, shape_report
from complyos.core.repository import LocalRepository
from complyos.models.domain import AssignmentRule
from complyos.services.ai_proposals import AIProposalService
from complyos.services.analytics import Granularity, TrendAnalyticsService
from complyos.services.attestations import AttestationService
from complyos.services.audit import AuditService
from complyos.services.connector_registry import ConnectorRegistry
from complyos.services.context import (
    ROLE_PERMISSIONS,
    ActorContext,
    AuthorizationError,
    default_local_context,
)
from complyos.services.evidence import EvidenceService
from complyos.services.governance import GovernancePacketService
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.inbound_hooks import InboundHookService, InboundWebhookSignatureError
from complyos.services.intake import IntakeService
from complyos.services.notifications import NotificationOutboxService
from complyos.services.policy_rules import PolicyRuleService
from complyos.services.privacy import PrivacyProgramService
from complyos.services.readiness import ReadinessService
from complyos.services.remediation import RemediationService
from complyos.services.role_admin import RoleAdminService
from complyos.services.rosters import RostersService
from complyos.services.security_evidence import SecurityEvidenceService
from complyos.services.source_intel import SourceIntelService
from complyos.web.rate_limit import RateLimitExceededError, check_rate_limit


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)
    request_id: str | None = None


class MappingProposalRequest(BaseModel):
    headers: list[str]
    target_schema: str = "learning_records"
    model_provider: str = "deterministic-local"
    model_name: str = "rules-v1"


class ImportDecisionRequest(BaseModel):
    row_id: str
    decision_type: str
    reason: str | None = None
    decision_payload: dict[str, object] = Field(default_factory=dict)


class PrivacyRequestBody(BaseModel):
    subject_id: str
    request_type: str
    region: str | None = None
    notes: str | None = None


class PrivacyApprovalBody(BaseModel):
    note: str | None = None


class LegalHoldRequestBody(BaseModel):
    subject_id: str | None = None
    scope: str = "subject"
    reason: str


class RetentionPolicyRequestBody(BaseModel):
    raw_import_days: int
    evidence_days: int
    action_log_days: int
    ai_proposal_days: int
    privacy_request_days: int = 365


class RetentionRunBody(BaseModel):
    dry_run: bool = True


class RemediationRequestBody(BaseModel):
    department: str | None = None
    region: str | None = None
    auto_remind: bool = True
    auto_enroll: bool = False
    notify_manager: bool = False


class ReportExportRequestBody(BaseModel):
    department: str | None = None
    region: str | None = None


class BiFeedExportRequestBody(BaseModel):
    format: str = "csv"


class SourceIntelDecisionBody(BaseModel):
    state: str


class NotificationPreferenceBody(BaseModel):
    channel: str
    event_type: str = "*"
    enabled: bool = True
    reason: str | None = None


class RoleBindingRequestBody(BaseModel):
    actor_id: str
    role: str
    permissions_override: list[str] | None = None


class AttestationRequirementBody(BaseModel):
    course_id: str
    code: str
    title: str
    category: str
    description: str | None = None


class AttestationRecordBody(BaseModel):
    user_id: str
    requirement_id: str
    policy_version: str
    expires_at: date | None = None
    on_behalf: bool = False


class IntakeSubmitBody(BaseModel):
    requester: str
    title: str
    audience: str | None = None
    priority: str | None = None
    business_context: str | None = None
    constraints: str | None = None
    requested_by_date: date | None = None


class IntakeConfirmBody(BaseModel):
    note: str | None = None


class RosterRequestBody(BaseModel):
    label: str
    csv_text: str
    source_system: str = "csv"


class RosterApproveBody(BaseModel):
    note: str | None = None


class RuleRequestBody(BaseModel):
    name: str
    target_criteria: dict[str, object] = Field(default_factory=dict)
    course_ids: list[str] = Field(default_factory=list)
    deadline_days: int = 30

    def to_rule(self) -> AssignmentRule:
        return AssignmentRule(
            name=self.name,
            target_criteria=dict(self.target_criteria),
            course_ids=list(self.course_ids),
            deadline_days_from_trigger=self.deadline_days,
        )


def _http_error(
    code: str,
    message: str,
    status_code: int,
    *,
    request_id: str | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail=ErrorBody(code=code, message=message, request_id=request_id).model_dump(),
    )


def _permission_error(exc: AuthorizationError, context: ActorContext) -> HTTPException:
    return _http_error(
        exc.code,
        str(exc),
        status.HTTP_403_FORBIDDEN,
        request_id=context.request_id,
    )


def _bad_request(code: str, exc: Exception, context: ActorContext) -> HTTPException:
    """Map a service exception to the right client status.

    A PermissionError (including AuthorizationError) is an authorization failure
    and must be 403, not 400 — several endpoints catch (PermissionError,
    ValueError) together, so classifying here keeps the status honest without a
    separate except clause at every call site. Validation errors stay 400.
    """
    status_code = (
        status.HTTP_403_FORBIDDEN
        if isinstance(exc, PermissionError)
        else status.HTTP_400_BAD_REQUEST
    )
    return _http_error(code, str(exc), status_code, request_id=context.request_id)


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


async def _rate_limit_guard(request: Request) -> None:
    """Router-level dependency enforcing the in-process mutating-endpoint quota.

    Runs per route so the matched path template is available for keying. On
    exceed it returns the project's structured 429 plus a Retry-After header.
    Read-only methods and an unset limit are no-ops (see web.rate_limit).
    """
    try:
        check_rate_limit(request)
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ErrorBody(
                code="rate_limited",
                message=f"rate limit of {exc.limit} requests/min exceeded; retry later",
                details={"limit_per_minute": exc.limit, "retry_after_seconds": exc.retry_after},
            ).model_dump(),
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc


def build_api_v1_router(repository: LocalRepository | None = None) -> APIRouter:
    repo = repository or LocalRepository()
    router = APIRouter(
        prefix="/api/v1",
        tags=["ComplyOS API v1"],
        dependencies=[Depends(_rate_limit_guard)],
    )

    async def actor_context(
        authorization: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str, Header()] = "local-default",
        x_track: Annotated[str, Header()] = "workforce",
        x_actor_id: Annotated[str, Header()] = "api-actor",
        x_actor_role: Annotated[str, Header()] = "owner",
    ) -> ActorContext:
        expected_token = os.getenv("COMPLYOS_API_TOKEN")
        if expected_token:
            expected_header = f"Bearer {expected_token}"
            # Constant-time comparison avoids a token-length/prefix timing side
            # channel on the only real auth gate for this PII surface.
            if not hmac.compare_digest(authorization or "", expected_header):
                raise _http_error(
                    "unauthorized",
                    "valid bearer token required",
                    status.HTTP_401_UNAUTHORIZED,
                )
            auth_method = "bearer"
        elif _truthy_env("COMPLYOS_ALLOW_INSECURE_LOCAL"):
            # Explicit, operator-acknowledged local/dev mode. Header-driven role
            # and tenant are trusted only because the operator opted in.
            auth_method = "local_dev"
        else:
            # Fail closed: never silently honor attacker-controlled X-Actor-Role/
            # X-Tenant-Id (which can request role=owner of any tenant) on an
            # unauthenticated surface. Require a bearer token, or an explicit
            # insecure opt-in for trusted local-only use.
            raise _http_error(
                "unauthorized",
                "API authentication is not configured: set COMPLYOS_API_TOKEN, or "
                "COMPLYOS_ALLOW_INSECURE_LOCAL=1 for trusted local-only use",
                status.HTTP_401_UNAUTHORIZED,
            )

        if x_actor_role not in ROLE_PERMISSIONS:
            raise _http_error(
                "invalid_role",
                f"unknown role: {x_actor_role}",
                status.HTTP_403_FORBIDDEN,
            )
        return default_local_context(
            surface="api",
            track=x_track,
            tenant_id=x_tenant_id,
            role=x_actor_role,
            actor_id=x_actor_id,
            auth_method=auth_method,
        )

    @router.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "complyos-api-v1"}

    @router.get("/readiness")
    async def readiness(
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return ReadinessService(repo).check(context).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    # ---- Audit/remediation parity with the CLI and MCP surfaces -------------
    # Plan §8.2/§7 specifies plural resource names (/audits, /learners,
    # /remediations). Those are the canonical paths; the original singular paths
    # are kept as deprecated aliases so existing clients keep working.
    @router.get("/audits")
    @router.get("/audit")
    async def audit(
        department: str | None = None,
        region: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            gaps, ledger = await AuditService(_get_connector(), repo).run_audit(
                context, department=department, region=region
            )
            return shape_gaps(gaps, ledger)
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.get("/report")
    async def report(
        department: str | None = None,
        region: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            audit_report = await AuditService(_get_connector(), repo).generate_report(
                context, department=department, region=region
            )
            return shape_report(audit_report)
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/exports/reports")
    async def export_report(
        body: ReportExportRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        # Remote report export gated at evidence:export. Unlike the CLI/MCP
        # file-writing export, this returns the rendered report content in the
        # response body and never writes to arbitrary server disk from a remote
        # call (plan §8.2). Underprivileged callers fail closed at the service.
        try:
            result = await EvidenceService(_get_connector(), repo).render_report(
                context, department=body.department, region=body.region
            )
            return {**result, "actor_context": context.public_dict()}
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.get("/learners/{user_id}/status")
    @router.get("/users/{user_id}/status")
    async def user_status(
        user_id: str,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return await AuditService(_get_connector(), repo).get_status(
                context, user_id=user_id
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.get("/digest")
    async def digest(
        department: str | None = None,
        region: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            result = await AuditService(_get_connector(), repo).get_digest(
                context, department=department, region=region
            )
            return result.model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.get("/analytics/trends")
    async def analytics_trends(
        granularity: str = "monthly",
        horizon_days: int = 30,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        # Tenant-scoped, period-bucketed trend metrics gated at analytics:read.
        # Scope comes from the context tenant, never a query param, so a caller
        # can only ever read their own tenant's records (plan §8.2 parity).
        try:
            bucket = Granularity(granularity)
        except ValueError as exc:
            raise _http_error(
                "invalid_granularity",
                "granularity must be 'weekly' or 'monthly'",
                status.HTTP_400_BAD_REQUEST,
                request_id=context.request_id,
            ) from exc
        try:
            result = TrendAnalyticsService(repo).compute(
                context, granularity=bucket, horizon_days=horizon_days
            )
            return {**result.model_dump(mode="json"), "actor_context": context.public_dict()}
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/exports/bi-feed")
    async def export_bi_feed(
        body: BiFeedExportRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        # Remote BI-feed export gated at evidence:export. Returns the rendered
        # CSV/JSON content in the response body and never writes to server disk
        # from a remote call. CSV is formula-injection neutralized at the writer.
        try:
            result = TrendAnalyticsService(repo).export_bi_feed(context, fmt=body.format)
            return {**result, "actor_context": context.public_dict()}
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _http_error(
                "invalid_format",
                str(exc),
                status.HTTP_400_BAD_REQUEST,
                request_id=context.request_id,
            ) from exc

    @router.get("/connectors")
    async def list_connectors(
        profile: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            connectors = ConnectorRegistry(_get_connector()).list(context, profile=profile)
            return {"connectors": connectors, "actor_context": context.public_dict()}
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_connector_profile", exc, context) from exc

    @router.get("/connectors/health")
    async def connector_health(
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return await ConnectorRegistry(_get_connector()).health(context)
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/rules/validate")
    async def validate_rule(
        body: RuleRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PolicyRuleService(repo).validate(context, body.to_rule())
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/rules/preview")
    async def preview_rule(
        body: RuleRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PolicyRuleService(repo).preview(context, body.to_rule())
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/remediations")
    @router.post("/remediate")
    async def remediate(
        body: RemediationRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            gaps, actions, ledger = await RemediationService(
                _get_connector(), notifier=_get_notifier()
            ).execute(
                context,
                department=body.department,
                region=body.region,
                auto_remind=body.auto_remind,
                auto_enroll=body.auto_enroll,
                notify_manager=body.notify_manager,
            )
            return shape_remediation(gaps, actions, ledger)
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/sync")
    async def sync(
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            result = await AuditService(_get_connector(), repo).sync(context)
            return {"synced": result, "actor_context": context.public_dict()}
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("sync_failed", exc, context) from exc

    @router.get("/admin/roles")
    async def list_role_bindings(
        actor_id: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return {
                "role_bindings": RoleAdminService(repo).list_role_bindings(
                    context, actor_id=actor_id
                ),
                "actor_context": context.public_dict(),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/admin/roles")
    async def set_role_binding(
        body: RoleBindingRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return RoleAdminService(repo).set_role_binding(
                context,
                actor_id=body.actor_id,
                role=body.role,
                permissions_override=body.permissions_override,
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_role_binding", exc, context) from exc

    @router.delete("/admin/roles/{actor_id}")
    async def remove_role_binding(
        actor_id: str,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return RoleAdminService(repo).remove_role_binding(context, actor_id=actor_id)
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("role_binding_not_found", exc, context) from exc

    @router.post("/imports/preview")
    async def preview_import(
        request: ImportPreviewRequest,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            if request.path:
                raise ValueError("API imports must use csv_text, not server-side file paths")
            return ImportService(repo).preview(context, request).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_import_request", exc, context) from exc

    @router.post("/imports/{batch_id}/decisions")
    async def decide_import_row(
        batch_id: str,
        request: ImportDecisionRequest,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return ImportService(repo).decide(
                context,
                batch_id=batch_id,
                row_id=request.row_id,
                decision_type=request.decision_type,
                reason=request.reason,
                decision_payload=dict(request.decision_payload),
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("bad_import_decision", exc, context) from exc

    @router.post("/imports/{batch_id}/promote")
    async def promote_import(
        batch_id: str,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return ImportService(repo).promote(context, batch_id).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("promotion_failed", exc, context) from exc

    @router.get("/evidence")
    async def evidence(
        limit: int = 50,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return {
                "items": EvidenceService(_get_connector(), repo).list_ledger(
                    context, limit=limit
                ),
                "actor_context": context.public_dict(),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.get("/security/evidence")
    async def collect_security_evidence(
        period: str = "current",
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return SecurityEvidenceService(repo).collect_packet(
                context,
                period=period,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.get("/governance/packet")
    async def collect_governance_packet(
        lane: str = "workforce",
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return GovernancePacketService(repo).collect_packet(
                context,
                lane=lane,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_governance_lane", exc, context) from exc

    @router.get("/source-intel/proposals")
    async def list_source_intel_proposals(
        state: str | None = None,
        limit: int = 50,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return {
                "proposals": SourceIntelService(repo).list_proposals(
                    context,
                    state=state,
                    limit=limit,
                ),
                "actor_context": context.public_dict(),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.get("/source-intel/export-packet")
    async def export_source_intel_review_packet(
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return SourceIntelService(repo).export_review_packet(context)
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/hooks/inbound/{source}")
    async def receive_inbound_hook(
        source: str,
        request: Request,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return InboundHookService(repo).record(
                context,
                source=source,
                body=await request.body(),
                headers=request.headers,
                signing_secret=os.getenv("COMPLYOS_INBOUND_WEBHOOK_SECRET"),
                require_signature=not _truthy_env("COMPLYOS_ALLOW_INSECURE_LOCAL"),
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except InboundWebhookSignatureError as exc:
            raise _http_error(
                exc.code,
                str(exc),
                status.HTTP_401_UNAUTHORIZED,
                request_id=context.request_id,
            ) from exc
        except ValueError as exc:
            raise _bad_request("bad_inbound_webhook", exc, context) from exc

    @router.get("/notifications/preferences")
    async def list_notification_preferences(
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return {
                "preferences": NotificationOutboxService(repo).list_preferences(context),
                "actor_context": context.public_dict(),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.put("/notifications/preferences")
    async def set_notification_preference(
        request: NotificationPreferenceBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return NotificationOutboxService(repo).set_preference(
                context,
                channel=request.channel,
                event_type=request.event_type,
                enabled=request.enabled,
                reason=request.reason,
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_notification_preference", exc, context) from exc

    @router.post("/source-intel/proposals/{proposal_id}/decision")
    async def decide_source_intel_proposal(
        proposal_id: str,
        request: SourceIntelDecisionBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return SourceIntelService(repo).decide_proposal(
                context,
                proposal_id=proposal_id,
                state=request.state,
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_source_intel_decision", exc, context) from exc

    @router.post("/ai/proposals/mapping")
    async def propose_mapping(
        request: MappingProposalRequest,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return AIProposalService(repo).propose_mapping(
                context,
                headers=request.headers,
                target_schema=request.target_schema,
                model_provider=request.model_provider,
                model_name=request.model_name,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    @router.post("/ai/proposals/{proposal_id}/approve")
    async def approve_ai_proposal(
        proposal_id: str,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return AIProposalService(repo).approve(context, proposal_id).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("proposal_approval_failed", exc, context) from exc

    @router.post("/privacy/requests")
    async def create_privacy_request(
        request: PrivacyRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).create_request(
                context,
                subject_id=request.subject_id,
                request_type=request.request_type,
                region=request.region,
                notes=request.notes,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_privacy_request", exc, context) from exc

    @router.post("/privacy/requests/{request_id}/approve")
    async def approve_privacy_request(
        request_id: str,
        request: PrivacyApprovalBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).approve_request(
                context,
                request_id,
                approval_note=request.note,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("privacy_approval_failed", exc, context) from exc

    @router.post("/privacy/requests/{request_id}/export")
    async def export_privacy_subject(
        request_id: str,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).export_subject(context, request_id).model_dump(
                mode="json"
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("privacy_export_failed", exc, context) from exc

    @router.post("/privacy/requests/{request_id}/delete")
    async def delete_privacy_subject(
        request_id: str,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).delete_subject(context, request_id).model_dump(
                mode="json"
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("privacy_delete_failed", exc, context) from exc

    @router.post("/privacy/legal-holds")
    async def create_legal_hold(
        request: LegalHoldRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).create_legal_hold(
                context,
                subject_id=request.subject_id,
                scope=request.scope,
                reason=request.reason,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_legal_hold", exc, context) from exc

    @router.post("/privacy/legal-holds/{hold_id}/release")
    async def release_legal_hold(
        hold_id: str,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).release_legal_hold(context, hold_id).model_dump(
                mode="json"
            )
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("legal_hold_release_failed", exc, context) from exc

    @router.post("/privacy/retention-policy")
    async def configure_retention_policy(
        request: RetentionPolicyRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).configure_retention_policy(
                context,
                raw_import_days=request.raw_import_days,
                evidence_days=request.evidence_days,
                action_log_days=request.action_log_days,
                ai_proposal_days=request.ai_proposal_days,
                privacy_request_days=request.privacy_request_days,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_retention_policy", exc, context) from exc

    @router.post("/privacy/retention-policy/run")
    async def run_retention_policy(
        request: RetentionRunBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return PrivacyProgramService(repo).run_retention_cleanup(
                context,
                dry_run=request.dry_run,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("retention_run_failed", exc, context) from exc

    # ---- AI-use-policy attestation / AI-literacy requirement tracking --------
    @router.post("/attestations/requirements")
    async def define_attestation_requirement(
        body: AttestationRequirementBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return AttestationService(repo).define_requirement(
                context,
                course_id=body.course_id,
                code=body.code,
                title=body.title,
                category=body.category,
                description=body.description,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_attestation_requirement", exc, context) from exc

    @router.post("/attestations")
    async def record_attestation(
        body: AttestationRecordBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return AttestationService(repo).record(
                context,
                user_id=body.user_id,
                requirement_id=body.requirement_id,
                policy_version=body.policy_version,
                expires_at=body.expires_at,
                on_behalf=body.on_behalf,
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("attestation_record_failed", exc, context) from exc

    @router.get("/attestations")
    async def list_attestations(
        user_id: str | None = None,
        requirement_id: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            records = AttestationService(repo).list_attestations(
                context, user_id=user_id, requirement_id=requirement_id
            )
            return {
                "items": [record.model_dump(mode="json") for record in records],
                "actor_context": context.public_dict(),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc

    # ---- Training intake: capture -> proposal-only packet -> confirm scope ----
    @router.post("/intake")
    async def submit_intake(
        body: IntakeSubmitBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            service = IntakeService(repo)
            request = service.create_request(
                context,
                requester=body.requester,
                title=body.title,
                audience=body.audience,
                priority=body.priority,
                business_context=body.business_context,
                constraints=body.constraints,
                requested_by_date=body.requested_by_date,
            )
            packet = service.draft_packet(context, request_id=request.id)
            return {
                "request": request.model_dump(mode="json"),
                "packet": packet.model_dump(mode="json"),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("intake_submit_failed", exc, context) from exc

    @router.get("/intake")
    async def list_intake(
        status: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            requests = IntakeService(repo).list_requests(context, status=status)
            return {
                "items": [req.model_dump(mode="json") for req in requests],
                "actor_context": context.public_dict(),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_intake_status", exc, context) from exc

    @router.post("/intake/{request_id}/confirm")
    async def confirm_intake_scope(
        request_id: str,
        body: IntakeConfirmBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return IntakeService(repo).confirm_scope(
                context, request_id=request_id, note=body.note
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("intake_confirm_failed", exc, context) from exc

    # ---- Rosters: preview/quarantine -> proposal-only view -> human-approved import ----
    @router.post("/rosters")
    async def request_roster_snapshot(
        body: RosterRequestBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            service = RostersService(repo)
            snapshot = service.request_snapshot(
                context,
                label=body.label,
                csv_text=body.csv_text,
                source_system=body.source_system,
            )
            packet = service.draft_packet(context, snapshot_id=snapshot.id)
            return {
                "snapshot": snapshot.model_dump(mode="json"),
                "packet": packet.model_dump(mode="json"),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("roster_request_failed", exc, context) from exc

    @router.get("/rosters")
    async def list_roster_snapshots(
        status: str | None = None,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            snapshots = RostersService(repo).list_snapshots(context, status=status)
            return {
                "items": [snap.model_dump(mode="json") for snap in snapshots],
                "actor_context": context.public_dict(),
            }
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except ValueError as exc:
            raise _bad_request("bad_roster_status", exc, context) from exc

    @router.post("/rosters/{snapshot_id}/approve")
    async def approve_roster_snapshot(
        snapshot_id: str,
        body: RosterApproveBody,
        context: ActorContext = Depends(actor_context),  # noqa: B008
    ) -> dict[str, object]:
        try:
            return RostersService(repo).approve_snapshot(
                context, snapshot_id=snapshot_id, note=body.note
            ).model_dump(mode="json")
        except AuthorizationError as exc:
            raise _permission_error(exc, context) from exc
        except (PermissionError, ValueError) as exc:
            raise _bad_request("roster_approve_failed", exc, context) from exc

    return router


def create_api_v1_app(repository: LocalRepository | None = None) -> FastAPI:
    app = FastAPI(title="ComplyOS API", version="0.1.0")
    app.include_router(build_api_v1_router(repository))
    return app
