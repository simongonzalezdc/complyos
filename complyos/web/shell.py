"""Authenticated enterprise web shell for ComplyOS (plan §10).

The shell is an APP, not a marketing page: side nav, top utility bar, dense
tables, and modules rendered from LIVE service data. It wraps the existing
ActorContext auth model in a SIGNED session cookie rather than inventing a second
auth model — the cookie carries only an opaque role token signed server-side, and
``shell_context`` rebuilds the SAME ActorContext that the services consume.

WP16a delivers the foundation (session login/logout, base layout, side nav) plus
the live Overview module. The remaining seven modules are present in the nav but
marked "soon" and land in WP16b-d.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import APIRouter, File, Form, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from complyos.api.mcp_server import _get_connector
from complyos.connectors.document import DocumentExtractionError, DocumentExtractor
from complyos.core.repository import LocalRepository
from complyos.models.domain import AuditReport
from complyos.notification.signing import sign_payload, verify_signature
from complyos.services.audit import AuditService
from complyos.services.context import (
    ROLE_PERMISSIONS,
    ActorContext,
    AuthorizationError,
    default_local_context,
)
from complyos.services.evidence import EvidenceService
from complyos.services.imports import (
    ImportIssue,
    ImportPreviewRequest,
    ImportPreviewResult,
    ImportService,
)
from complyos.services.privacy import PrivacyProgramService
from complyos.services.readiness import ReadinessService
from complyos.services.remediation import RemediationService
from complyos.services.role_admin import RoleAdminService
from complyos.services.source_intel import SourceIntelService
from complyos.web.api_v1 import _truthy_env

_HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = _HERE / "templates"
STATIC_DIR = _HERE / "static"

SHELL_PREFIX = "/shell"
STATIC_PREFIX = "/shell/static"
SESSION_COOKIE = "complyos_shell"

# Plan §10 — the enterprise modules. Overview + Gaps/Imports/Evidence are live
# (WP16a/16b); the rest remain "soon" and land in WP16c-d.
MODULES: tuple[dict[str, object], ...] = (
    {"key": "overview", "label": "Overview", "href": SHELL_PREFIX, "live": True},
    {"key": "gaps", "label": "Gaps", "href": f"{SHELL_PREFIX}/gaps", "live": True},
    {"key": "imports", "label": "Imports", "href": f"{SHELL_PREFIX}/imports", "live": True},
    {"key": "records", "label": "Records", "href": f"{SHELL_PREFIX}/records", "live": True},
    {"key": "evidence", "label": "Evidence", "href": f"{SHELL_PREFIX}/evidence", "live": True},
    {
        "key": "remediation",
        "label": "Remediation",
        "href": f"{SHELL_PREFIX}/remediation",
        "live": True,
    },
    {
        "key": "source_intel",
        "label": "Source intelligence",
        "href": f"{SHELL_PREFIX}/source-intel",
        "live": True,
    },
    {
        "key": "privacy",
        "label": "Privacy & retention",
        "href": f"{SHELL_PREFIX}/privacy",
        "live": True,
    },
    {"key": "readiness", "label": "Readiness", "href": f"{SHELL_PREFIX}/readiness", "live": True},
    {"key": "admin", "label": "Administration", "href": f"{SHELL_PREFIX}/admin", "live": True},
)

# Gap queue ordering: most severe first.
SEVERITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}


class AuditReporter(Protocol):
    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        """Generate an audit report."""


def _session_secret() -> str | None:
    """Server secret used to sign session cookies.

    Prefer an explicit session secret; otherwise reuse the API token so the shell
    shares the deployment's existing credential. Returns None when neither is set
    (the fail-closed/insecure-local paths handle that case).
    """
    secret = os.getenv("COMPLYOS_SESSION_SECRET") or os.getenv("COMPLYOS_API_TOKEN")
    return secret.strip() if secret else None


def _sign_role(role: str, secret: str) -> str:
    """Sign a role into an opaque, tamper-evident cookie value.

    Format: ``<role>.<signature>`` where the signature is the canonical ComplyOS
    HMAC-SHA256 over the role bytes (itsdangerous is not a dependency, so we reuse
    notification.signing — one audited HMAC implementation). The client never
    receives a forgeable plaintext role it can swap for ``owner``: any edit
    invalidates the signature.
    """
    signature = sign_payload(secret, timestamp="shell-session", body=role.encode("utf-8"))
    return f"{role}.{signature}"


def _verify_cookie(value: str | None, secret: str) -> str | None:
    """Return the role from a valid signed cookie, else None (constant-time)."""
    if not value:
        return None
    role, _, signature = value.partition(".")
    if not role or not signature:
        return None
    if not verify_signature(
        secret, timestamp="shell-session", body=role.encode("utf-8"), signature=signature
    ):
        return None
    if role not in ROLE_PERMISSIONS:
        return None
    return role


def build_shell_router(
    *,
    auditor: AuditReporter,
    repository: LocalRepository,
) -> APIRouter:
    """Build the authenticated shell router (mounted by the dashboard app)."""
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    router = APIRouter()

    def _login_redirect() -> RedirectResponse:
        return RedirectResponse(f"{SHELL_PREFIX}/login", status_code=status.HTTP_302_FOUND)

    def _shell_context(request: Request) -> ActorContext | None:
        """Read + verify the session cookie and rebuild the service ActorContext."""
        secret = _session_secret()
        if secret:
            role = _verify_cookie(request.cookies.get(SESSION_COOKIE), secret)
            if role is None:
                return None
            auth_method = "session"
        elif _truthy_env("COMPLYOS_ALLOW_INSECURE_LOCAL"):
            role = _verify_cookie(request.cookies.get(SESSION_COOKIE), "insecure-local")
            if role is None:
                return None
            auth_method = "local_dev"
        else:
            return None
        return default_local_context(surface="shell", role=role, auth_method=auth_method)

    def _set_session(response: Response, role: str) -> None:
        secret = _session_secret() or "insecure-local"
        response.set_cookie(
            SESSION_COOKIE,
            _sign_role(role, secret),
            httponly=True,
            samesite="lax",
            # Local-first default is HTTP, so Secure is off and a TLS
            # terminator/proxy owns it in prod; flip COMPLYOS_SESSION_SECURE to
            # mark the cookie Secure when the console is served over HTTPS.
            secure=_truthy_env("COMPLYOS_SESSION_SECURE"),
            path=SHELL_PREFIX,
        )

    def _render(
        request: Request,
        name: str,
        ctx: dict[str, object],
        *,
        status_code: int = status.HTTP_200_OK,
    ) -> Response:
        base: dict[str, object] = {
            "request": request,
            "static_url": STATIC_PREFIX,
            "shell_url": SHELL_PREFIX,
            "modules": MODULES,
        }
        base.update(ctx)
        return templates.TemplateResponse(request, name, base, status_code=status_code)

    def _permission_panel(
        request: Request,
        *,
        active: str,
        context: ActorContext,
        module_label: str,
        error: AuthorizationError,
    ) -> Response:
        """Render the inline permission panel inside the shell (HTTP 200).

        Mirrors the source-intel try/except in ``_overview_view``: a role that
        lacks a module's permission keeps the shell chrome and sees a clear panel
        naming the missing permission, rather than a 500 or a torn-down page.
        """
        return _render(
            request,
            "permission_denied.html",
            {
                "active": active,
                "context": context,
                "module_label": module_label,
                "needed_permission": error.permission,
            },
        )

    def _login_error(request: Request, message: str) -> Response:
        local_mode = _session_secret() is None and _truthy_env("COMPLYOS_ALLOW_INSECURE_LOCAL")
        return _render(
            request,
            "login.html",
            {"local_mode": local_mode, "roles": sorted(ROLE_PERMISSIONS), "error": message},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    @router.get("/shell/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> Response:
        local_mode = _session_secret() is None and _truthy_env("COMPLYOS_ALLOW_INSECURE_LOCAL")
        return _render(
            request,
            "login.html",
            {
                "local_mode": local_mode,
                "roles": sorted(ROLE_PERMISSIONS),
                "error": None,
            },
        )

    @router.post("/shell/login")
    async def login(
        request: Request,
        token: str = Form(default=""),
        role: str = Form(default=""),
    ) -> Response:
        secret = _session_secret()
        if secret:
            # Bearer-token parity with the API: constant-time compare, then the
            # signed cookie pins role=owner (the API's default privileged role).
            if not token or not hmac.compare_digest(token, secret):
                return _login_error(request, "Invalid API token.")
            session_role = "owner"
        elif _truthy_env("COMPLYOS_ALLOW_INSECURE_LOCAL"):
            session_role = role if role in ROLE_PERMISSIONS else "owner"
        else:
            # Fail closed: no token configured and no insecure opt-in — refuse,
            # exactly like the API's actor_context dependency.
            return _login_error(request, "Console authentication is not configured.")

        response = RedirectResponse(SHELL_PREFIX, status_code=status.HTTP_303_SEE_OTHER)
        _set_session(response, session_role)
        return response

    @router.post("/shell/logout")
    async def logout() -> Response:
        response = RedirectResponse(
            f"{SHELL_PREFIX}/login", status_code=status.HTTP_303_SEE_OTHER
        )
        response.delete_cookie(SESSION_COOKIE, path=SHELL_PREFIX)
        return response

    async def _overview_view(request: Request) -> Response:
        context = _shell_context(request)
        if context is None:
            return _login_redirect()

        report = await auditor.generate_report()
        try:
            readiness = ReadinessService(repository).check(context)
            readiness_summary = sorted(readiness.summary.items(), key=lambda kv: kv[0])
            readiness_designed = readiness.summary.get("designed", 0)
            readiness_total = len(readiness.controls)
            readiness_posture = readiness.posture
        except AuthorizationError:
            # A role without readiness:read still gets an Overview; the readiness
            # tile reports "restricted" rather than 500-ing the landing page.
            readiness_summary = []
            readiness_designed = 0
            readiness_total = 0
            readiness_posture = "restricted"
        try:
            pending_signals = len(
                SourceIntelService(repository).list_proposals(context, limit=100)
            )
        except AuthorizationError:
            # Roles without source_intel:read still get an Overview; the signal
            # tile just reports zero rather than 403-ing the whole page.
            pending_signals = 0

        severity_order = ("critical", "high", "medium", "low")
        gaps_by_severity = [
            (sev, report.gaps_by_severity.get(sev, 0)) for sev in severity_order
        ]
        high_risk = report.gaps_by_severity.get("high", 0) + report.gaps_by_severity.get(
            "critical", 0
        )

        overview = {
            "gaps_found": report.gaps_found,
            "total_users_audited": report.total_users_audited,
            "high_risk_gaps": high_risk,
            "gaps_by_severity": gaps_by_severity,
            "readiness_designed": readiness_designed,
            "readiness_total": readiness_total,
            "readiness_summary": readiness_summary,
            "readiness_posture": readiness_posture,
            "pending_signals": pending_signals,
        }
        return _render(
            request,
            "overview.html",
            {"active": "overview", "context": context, "overview": overview},
        )

    @router.get("/shell", response_class=HTMLResponse)
    async def shell_root(request: Request) -> Response:
        return await _overview_view(request)

    @router.get("/shell/overview", response_class=HTMLResponse)
    async def shell_overview(request: Request) -> Response:
        return await _overview_view(request)

    @router.get("/shell/gaps", response_class=HTMLResponse)
    async def shell_gaps(request: Request, severity: str | None = None) -> Response:
        """Learner/worker compliance gap queue (plan §10), from live AuditService."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            gaps, _ledger = await AuditService(_get_connector(), repository).run_audit(
                context
            )
        except AuthorizationError as exc:
            return _permission_panel(
                request, active="gaps", context=context, module_label="Gaps", error=exc
            )

        severity_filter = severity.strip().lower() if severity else None
        rows = [
            {
                "user_id": gap.user.id,
                "department": gap.user.department,
                "missing_courses": [course.title for course in gap.missing_courses],
                "days_overdue": gap.days_overdue,
                "severity": gap.severity,
            }
            for gap in gaps
            if severity_filter is None or gap.severity == severity_filter
        ]
        rows.sort(key=lambda row: SEVERITY_RANK.get(str(row["severity"]), 99))
        return _render(
            request,
            "gaps.html",
            {
                "active": "gaps",
                "context": context,
                "rows": rows,
                "total_gaps": len(gaps),
                "severity_filter": severity_filter,
                "severities": ("critical", "high", "medium", "low"),
            },
        )

    def _imports_render(
        request: Request,
        context: ActorContext,
        *,
        preview: object | None = None,
        rows: list[dict[str, object]] | None = None,
        promotion_status: str | None = None,
    ) -> Response:
        return _render(
            request,
            "imports.html",
            {
                "active": "imports",
                "context": context,
                "preview": preview,
                "rows": rows or [],
                "promotion_status": promotion_status,
            },
        )

    def _reload_import_preview(
        service: ImportService,
        context: ActorContext,
        batch_id: str,
    ) -> ImportPreviewResult | None:
        """Rebuild the preview view of a stored batch (read-only, no mutation).

        Mirrors the existing-batch branch of ImportService.preview so a re-render
        after a decide/promote shows the batch's current persisted state without
        re-running validation or touching the LMS.
        """
        batch = repository.get_import_batch(batch_id)
        if batch is None or batch["tenant_id"] != context.tenant_id:
            return None
        batch_rows = repository.list_import_rows(batch_id)
        issues = [
            ImportIssue(**issue) for row in batch_rows for issue in row.get("issues", [])
        ]
        return ImportPreviewResult(
            batch_id=batch["id"],
            tenant_id=batch["tenant_id"],
            source_system=batch["source_system"],
            profile=batch["profile"],
            status=batch["status"],
            idempotency_key=batch["idempotency_key"],
            raw_file_hash=batch["raw_file_hash"],
            total_rows=len(batch_rows),
            row_counts=service._row_counts(batch_rows),
            unexpected_columns=sorted(
                {
                    issue.column
                    for issue in issues
                    if issue.code == "UNEXPECTED_COLUMN" and issue.column
                }
            ),
            issues=issues,
            can_promote=service._can_promote_rows(batch_rows),
            rows_preview=[row["normalized_payload"] for row in batch_rows[:10]],
            actor_context=context.public_dict(),
        )

    def _import_decision_rows(batch_id: str) -> list[dict[str, object]]:
        """Per-row id/status/payload for the imports decision controls."""
        return [
            {
                "id": row["id"],
                "row_number": row["row_number"],
                "validation_status": row["validation_status"],
                "user_id": row["normalized_payload"].get("user_id", ""),
                "course_id": row["normalized_payload"].get("course_id", ""),
            }
            for row in repository.list_import_rows(batch_id)
        ]

    @router.get("/shell/imports", response_class=HTMLResponse)
    async def shell_imports(request: Request) -> Response:
        """Import lifecycle surface (plan §10): paste/upload form + last preview."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        return _imports_render(request, context)

    @router.post("/shell/imports/preview", response_class=HTMLResponse)
    async def shell_imports_preview(
        request: Request,
        csv_text: Annotated[str, Form()] = "",
        document_file: Annotated[UploadFile | None, File()] = None,
    ) -> Response:
        """Preview pasted CSV or uploaded document rows through ImportService."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        source_system = "csv"
        preview_csv_text = csv_text
        if document_file is not None and document_file.filename:
            source_system = "document_upload"
            content = await document_file.read()
            try:
                preview_csv_text = DocumentExtractor(
                    content,
                    filename=document_file.filename,
                ).to_import_csv_text()
            except DocumentExtractionError:
                preview_csv_text = ""
        try:
            preview = ImportService(repository).preview(
                context,
                ImportPreviewRequest(source_system=source_system, csv_text=preview_csv_text),
            )
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="imports",
                context=context,
                module_label="Imports",
                error=exc,
            )
        return _imports_render(
            request, context, preview=preview, rows=_import_decision_rows(preview.batch_id)
        )

    @router.get("/shell/records", response_class=HTMLResponse)
    async def shell_records(request: Request) -> Response:
        """Read normalized training records and renewal status."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            rows = EvidenceService(_get_connector(), repository).list_training_record_status(
                context
            )
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="records",
                context=context,
                module_label="Records",
                error=exc,
            )
        return _render(
            request,
            "records.html",
            {"active": "records", "context": context, "rows": rows},
        )

    @router.get("/shell/records/export.csv")
    async def shell_records_export_csv(request: Request) -> Response:
        """Export the client-facing status packet as CSV."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            content = EvidenceService(
                _get_connector(),
                repository,
            ).render_training_record_packet_csv(
                context,
            )
        except AuthorizationError:
            return Response("permission denied", status_code=status.HTTP_403_FORBIDDEN)
        return Response(
            content,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    'attachment; filename="client-facing-status-packet.csv"'
                )
            },
        )

    @router.get("/shell/records/export.html", response_class=HTMLResponse)
    async def shell_records_export_html(request: Request) -> Response:
        """Export the client-facing status packet as minimal HTML."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            content = EvidenceService(
                _get_connector(),
                repository,
            ).render_training_record_packet_html(context)
        except AuthorizationError:
            return Response("permission denied", status_code=status.HTTP_403_FORBIDDEN)
        return HTMLResponse(content)

    @router.get("/shell/evidence", response_class=HTMLResponse)
    async def shell_evidence(request: Request, limit: int = 50) -> Response:
        """Evidence ledger (plan §10), from the live EvidenceService."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            entries = EvidenceService(_get_connector(), repository).list_ledger(
                context, limit=max(1, min(limit, 500))
            )
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="evidence",
                context=context,
                module_label="Evidence",
                error=exc,
            )
        return _render(
            request,
            "evidence.html",
            {"active": "evidence", "context": context, "entries": entries},
        )

    @router.get("/shell/remediation", response_class=HTMLResponse)
    async def shell_remediation(request: Request) -> Response:
        """Remediation queue as a non-mutating dry-run proposal (remediation:propose).

        Calls RemediationService.propose — the dry-run path that computes the
        actions that *would* run without sending reminders, enrolling, or
        notifying. Execution is rendered as a clearly-labeled control that
        requires explicit approval; this GET never mutates.
        """
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            _gaps, actions, _ledger = await RemediationService(_get_connector()).propose(context)
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="remediation",
                context=context,
                module_label="Remediation",
                error=exc,
            )
        rows = [
            {
                "user_id": action.user_id,
                "course_id": action.course_id,
                "action_type": action.action_type,
                "status": action.status,
            }
            for action in actions
        ]
        return _render(
            request,
            "remediation.html",
            {"active": "remediation", "context": context, "rows": rows},
        )

    @router.get("/shell/source-intel", response_class=HTMLResponse)
    async def shell_source_intel(request: Request, limit: int = 100) -> Response:
        """Regulatory source-signal review queue (source_intel:read)."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            proposals = SourceIntelService(repository).list_proposals(
                context, limit=max(1, min(limit, 500))
            )
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="source_intel",
                context=context,
                module_label="Source intelligence",
                error=exc,
            )
        return _render(
            request,
            "source_intel.html",
            {"active": "source_intel", "context": context, "proposals": proposals},
        )

    @router.get("/shell/privacy", response_class=HTMLResponse)
    async def shell_privacy(request: Request) -> Response:
        """Privacy/DSR + retention posture as a read-only panel (privacy:request).

        The PrivacyProgramService exposes no list/status read API for requests —
        only mutating export/delete and the create/approve workflow — so this GET
        renders a read-only posture surface. Legal holds and the retention policy
        come from the repository's read-safe methods; pending DSR actions are
        described and deferred. No mutating method is ever called from this GET.
        """
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        # Route the read through PrivacyProgramService so the service layer is the
        # single authorization choke-point (privacy:request). A role lacking the
        # permission gets the inline panel rather than a posture page it shouldn't
        # see, and the shell no longer reaches into the repository directly.
        try:
            posture = PrivacyProgramService(repository).get_privacy_posture(context)
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="privacy",
                context=context,
                module_label="Privacy & retention",
                error=exc,
            )
        return _render(
            request,
            "privacy.html",
            {
                "active": "privacy",
                "context": context,
                "holds": posture.active_legal_holds,
                "retention_policy": sorted(posture.retention_policy.as_mapping().items()),
            },
        )

    @router.get("/shell/readiness", response_class=HTMLResponse)
    async def shell_readiness(request: Request) -> Response:
        """Control readiness matrix from the live ReadinessService (readiness:read)."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            report = ReadinessService(repository).check(context)
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="readiness",
                context=context,
                module_label="Readiness",
                error=exc,
            )
        summary = sorted(report.summary.items(), key=lambda kv: kv[0])
        return _render(
            request,
            "readiness.html",
            {
                "active": "readiness",
                "context": context,
                "controls": report.controls,
                "summary": summary,
                "posture": report.posture,
                "tenant_metadata": report.tenant_metadata,
            },
        )

    @router.get("/shell/admin", response_class=HTMLResponse)
    async def shell_admin(request: Request) -> Response:
        """Tenant-scoped role-binding administration (admin:manage)."""
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        try:
            bindings = RoleAdminService(repository).list_role_bindings(context)
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="admin",
                context=context,
                module_label="Administration",
                error=exc,
            )
        return _render(
            request,
            "admin.html",
            {"active": "admin", "context": context, "bindings": bindings},
        )

    @router.post("/shell/imports/{batch_id}/decisions", response_class=HTMLResponse)
    async def shell_imports_decide(
        request: Request,
        batch_id: str,
        row_id: str = Form(...),
        decision_type: str = Form(...),
    ) -> Response:
        """Record an operator decision on one quarantined row (import:decide).

        Re-renders the imports view over the batch's updated state so a row moved
        out of NEEDS_DECISION (e.g. accepted) is reflected immediately.
        """
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        service = ImportService(repository)
        try:
            service.decide(
                context,
                batch_id=batch_id,
                row_id=row_id,
                decision_type=decision_type,
            )
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="imports",
                context=context,
                module_label="Imports",
                error=exc,
            )
        preview = _reload_import_preview(service, context, batch_id)
        return _imports_render(
            request, context, preview=preview, rows=_import_decision_rows(batch_id)
        )

    @router.post("/shell/imports/{batch_id}/promote", response_class=HTMLResponse)
    async def shell_imports_promote(request: Request, batch_id: str) -> Response:
        """Promote a batch on explicit operator submit (import:promote).

        Fail-closed behavior is preserved by the service: a batch with any
        blocking row stays QUARANTINED. The post-promote state is re-rendered.
        """
        context = _shell_context(request)
        if context is None:
            return _login_redirect()
        service = ImportService(repository)
        try:
            result = service.promote(context, batch_id)
        except AuthorizationError as exc:
            return _permission_panel(
                request,
                active="imports",
                context=context,
                module_label="Imports",
                error=exc,
            )
        preview = _reload_import_preview(service, context, batch_id)
        return _imports_render(
            request,
            context,
            preview=preview,
            rows=_import_decision_rows(batch_id),
            promotion_status=result.status,
        )

    return router


def mount_shell(app, *, auditor: AuditReporter, repository: LocalRepository) -> None:
    """Mount the shell router and its static files onto an existing app."""
    from fastapi.staticfiles import StaticFiles

    app.include_router(build_shell_router(auditor=auditor, repository=repository))
    app.mount(STATIC_PREFIX, StaticFiles(directory=str(STATIC_DIR)), name="shell-static")
