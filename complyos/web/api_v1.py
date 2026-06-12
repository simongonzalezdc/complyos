"""Versioned FastAPI API over ComplyOS application services."""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from complyos.core.repository import LocalRepository
from complyos.services.ai_proposals import AIProposalService
from complyos.services.context import (
    ROLE_PERMISSIONS,
    ActorContext,
    AuthorizationError,
    default_local_context,
)
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.readiness import ReadinessService


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
            if authorization != expected_header:
                raise _http_error(
                    "unauthorized",
                    "valid bearer token required",
                    status.HTTP_401_UNAUTHORIZED,
                )
            auth_method = "bearer"
        else:
            # Local-first/dev mode remains explicit and context-backed. Production
            # deployments must set COMPLYOS_API_TOKEN or replace this dependency.
            auth_method = "local_dev"

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
            "items": repo.list_evidence_ledger(limit=limit),
            "actor_context": context.public_dict(),
        }

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

    return router


def create_api_v1_app(repository: LocalRepository | None = None) -> FastAPI:
    app = FastAPI(title="ComplyOS API", version="0.1.0")
    app.include_router(build_api_v1_router(repository))
    return app
