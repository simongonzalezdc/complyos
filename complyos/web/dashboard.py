"""Live FastAPI dashboard for ComplyOS."""

from __future__ import annotations

import os
import tempfile
from html import escape
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse

from complyos.core.dashboard import generate_dashboard
from complyos.core.repository import LocalRepository
from complyos.models.domain import AuditReport
from complyos.services.context import default_local_context
from complyos.services.source_intel import SourceIntelService
from complyos.web.api_v1 import _truthy_env, build_api_v1_router


def _guard_legacy_dev_endpoint() -> None:
    """Refuse to serve the legacy unauthenticated endpoints in a secured posture.

    The /api/audit, /api/summary, and /dashboard routes below are local/dev only
    and carry no authentication. When the operator has configured a real auth
    gate (COMPLYOS_API_TOKEN) without explicitly opting into insecure local use
    (COMPLYOS_ALLOW_INSECURE_LOCAL), these unauthenticated routes must fail
    closed so they cannot leak compliance data alongside the authenticated v1
    API. With no token set (plain local dev), behavior is unchanged.
    """
    if os.getenv("COMPLYOS_API_TOKEN") and not _truthy_env("COMPLYOS_ALLOW_INSECURE_LOCAL"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="legacy unauthenticated endpoint disabled in secured posture",
        )


class AuditReporter(Protocol):
    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        """Generate an audit report."""


def create_dashboard_app(
    *,
    auditor: AuditReporter,
    repository: LocalRepository | None = None,
) -> FastAPI:
    """Create the live ComplyOS dashboard app."""
    repo = repository or LocalRepository()
    app = FastAPI(title="ComplyOS Dashboard", version="0.1.0")
    app.include_router(build_api_v1_router(repo))

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "complyos-dashboard"}

    @app.get("/api/audit")
    async def api_audit(
        department: str | None = None,
        region: str | None = None,
    ) -> dict:
        """Local/dev only: unauthenticated audit report (disabled in secured posture)."""
        _guard_legacy_dev_endpoint()
        report = await auditor.generate_report(department=department, region=region)
        return report.model_dump(mode="json")

    @app.get("/api/summary")
    async def api_summary(
        department: str | None = None,
        region: str | None = None,
    ) -> dict:
        """Local/dev only: unauthenticated audit summary (disabled in secured posture)."""
        _guard_legacy_dev_endpoint()
        report = await auditor.generate_report(department=department, region=region)
        return {
            "generated_at": report.generated_at.isoformat(),
            "scope": report.scope,
            "total_users_audited": report.total_users_audited,
            "gaps_found": report.gaps_found,
            "gaps_by_severity": report.gaps_by_severity,
            "gaps_by_department": report.gaps_by_department,
            "top_missing_courses": report.top_missing_courses,
            "evidence_hash": report.evidence_hash,
        }

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(
        department: str | None = None,
        region: str | None = None,
    ) -> HTMLResponse:
        """Local/dev only: unauthenticated HTML dashboard (disabled in secured posture)."""
        _guard_legacy_dev_endpoint()
        report = await auditor.generate_report(department=department, region=region)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dashboard.html"
            generate_dashboard(report, output_path=str(output))
            return HTMLResponse(output.read_text(encoding="utf-8"))

    @app.get("/source-intel/review", response_class=HTMLResponse)
    async def source_intel_review() -> HTMLResponse:
        context = default_local_context(
            surface="dashboard",
            role="compliance_manager",
        )
        proposals = SourceIntelService(repo).list_proposals(context, limit=100)
        rows = "\n".join(
            "<tr>"
            f"<td><code>{escape(str(proposal['id']))}</code></td>"
            f"<td>{escape(str(proposal['adapter_name']))}</td>"
            f"<td>{escape(str(proposal['signal_type']))}</td>"
            f"<td><strong>{escape(str(proposal['approval_state']))}</strong></td>"
            f"<td>{escape(str(proposal.get('title') or 'Untitled source signal'))}</td>"
            f"<td>{escape(str(proposal.get('summary') or ''))}</td>"
            "</tr>"
            for proposal in proposals
        )
        if not rows:
            rows = (
                "<tr><td colspan='6'>No source-intelligence proposals are waiting for review."
                "</td></tr>"
            )
        html = f"""
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8" />
          <meta name="viewport" content="width=device-width, initial-scale=1" />
          <title>Source Intelligence Review Queue · ComplyOS</title>
          <style>
            body {{
              margin: 0;
              font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI";
              background: #0e1116;
              color: #f4f7fb;
            }}
            main {{ padding: 32px; }}
            .eyebrow {{
              color: #91a7c7;
              font-size: 12px;
              font-weight: 700;
              letter-spacing: 0.12em;
              text-transform: uppercase;
            }}
            h1 {{ margin: 8px 0 12px; font-size: 32px; }}
            p {{ color: #bac6d8; max-width: 820px; }}
            table {{
              border-collapse: collapse;
              width: 100%;
              margin-top: 24px;
              background: #141a23;
              border: 1px solid #2a3444;
            }}
            th, td {{
              border-bottom: 1px solid #2a3444;
              padding: 12px;
              text-align: left;
              vertical-align: top;
              font-size: 14px;
            }}
            th {{ color: #91a7c7; text-transform: uppercase; font-size: 11px; }}
            code {{
              color: #9ee493;
              font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
              font-size: 12px;
            }}
          </style>
        </head>
        <body>
          <main>
            <div class="eyebrow">Human approval required</div>
            <h1>Source Intelligence Review Queue</h1>
            <p>
              Proposals from RegWatch and Microlearning Radar stay here until a human
              reviewer approves, rejects, or supersedes them. No rule, course, or module
              is published automatically.
            </p>
            <table>
              <thead>
                <tr>
                  <th>Proposal</th>
                  <th>Adapter</th>
                  <th>Signal</th>
                  <th>State</th>
                  <th>Title</th>
                  <th>Summary</th>
                </tr>
              </thead>
              <tbody>{rows}</tbody>
            </table>
          </main>
        </body>
        </html>
        """
        return HTMLResponse(html)

    return app
