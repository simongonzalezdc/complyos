"""Versioned FastAPI API over ComplyOS application services."""

from __future__ import annotations

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import AIProposalService
from complyos.services.context import (
    ROLE_PERMISSIONS,
    ActorContext,
    AuthorizationError,
    default_local_context,
)
from complyos.services.governance import GovernancePacketService
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.inbound_hooks import InboundHookService, InboundWebhookSignatureError
from complyos.services.notifications import NotificationOutboxService
from complyos.services.privacy import PrivacyProgramService
from complyos.services.readiness import ReadinessService
from complyos.services.security_evidence import SecurityEvidenceService
from complyos.services.source_intel import SourceIntelService


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


class SourceIntelDecisionBody(BaseModel):
    state: str


class NotificationPreferenceBody(BaseModel):
    channel: str
    event_type: str = "*"
    enabled: bool = True
    reason: str | None = None


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
    return _http_error(
        code,
        str(exc),
        status.HTTP_400_BAD_REQUEST,
        request_id=context.request_id,
    )


def _truthy_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def build_api_v1_router(repository: LocalRepository | None = None) -> APIRouter:
    repo = repository or LocalRepository()
    router = APIRouter(prefix="/api/v1", tags=["ComplyOS API v1"])

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
        except ValueError as exc:
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
        if not context.has_permission("evidence:read"):
            raise _http_error(
                "permission_denied",
                "evidence:read required",
                status.HTTP_403_FORBIDDEN,
                request_id=context.request_id,
            )
        return {
            "items": repo.list_evidence_ledger(tenant_id=context.tenant_id, limit=limit),
            "actor_context": context.public_dict(),
        }

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

    return router


def create_api_v1_app(repository: LocalRepository | None = None) -> FastAPI:
    app = FastAPI(title="ComplyOS API", version="0.1.0")
    app.include_router(build_api_v1_router(repository))
    return app
