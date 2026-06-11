"""Tests for the live dashboard FastAPI app."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from complyos.models.domain import AuditReport
from complyos.web.dashboard import create_dashboard_app


class FakeAuditor:
    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        return AuditReport(
            generated_at=datetime(2026, 6, 11, 12, 0, tzinfo=UTC),
            scope=f"department={department}, region={region}" if department or region else "all",
            total_users_audited=5,
            gaps_found=1,
            gaps_by_severity={"low": 0, "medium": 1, "high": 0, "critical": 0},
            gaps_by_department={"Operations": 1},
            top_missing_courses=[("Safety", 1)],
            evidence_hash="hash-live",
            details=[],
        )


def test_live_dashboard_health() -> None:
    client = TestClient(create_dashboard_app(auditor=FakeAuditor()))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "complyos-dashboard"}


def test_live_dashboard_summary_endpoint() -> None:
    client = TestClient(create_dashboard_app(auditor=FakeAuditor()))

    response = client.get("/api/summary?department=Operations")

    assert response.status_code == 200
    assert response.json()["scope"] == "department=Operations, region=None"
    assert response.json()["gaps_found"] == 1
    assert response.json()["evidence_hash"] == "hash-live"


def test_live_dashboard_html_endpoint() -> None:
    client = TestClient(create_dashboard_app(auditor=FakeAuditor()))

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "ComplyOS Dashboard" in response.text
    assert "hash-live" in response.text
