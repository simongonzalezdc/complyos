"""Live FastAPI dashboard for ComplyOS."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from complyos.core.dashboard import generate_dashboard
from complyos.models.domain import AuditReport
from complyos.web.api_v1 import build_api_v1_router


class AuditReporter(Protocol):
    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        """Generate an audit report."""


def create_dashboard_app(*, auditor: AuditReporter) -> FastAPI:
    """Create the live ComplyOS dashboard app."""
    app = FastAPI(title="ComplyOS Dashboard", version="0.1.0")
    app.include_router(build_api_v1_router())

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "complyos-dashboard"}

    @app.get("/api/audit")
    async def api_audit(
        department: str | None = None,
        region: str | None = None,
    ) -> dict:
        report = await auditor.generate_report(department=department, region=region)
        return report.model_dump(mode="json")

    @app.get("/api/summary")
    async def api_summary(
        department: str | None = None,
        region: str | None = None,
    ) -> dict:
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
        report = await auditor.generate_report(department=department, region=region)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dashboard.html"
            generate_dashboard(report, output_path=str(output))
            return HTMLResponse(output.read_text(encoding="utf-8"))

    return app
