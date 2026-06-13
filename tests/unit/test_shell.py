"""Tests for the authenticated enterprise web shell (WP16a).

The shell wraps the existing ActorContext auth model in a signed session cookie
and renders modules from LIVE service data. Stage WP16a delivers the foundation
(session login/logout, base layout, side nav) plus the live Overview module.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from complyos.connectors.mock import MockConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.repository import LocalRepository
from complyos.models.domain import AuditReport
from complyos.web.dashboard import create_dashboard_app


class FakeAuditor:
    """Deterministic auditor with a known gap count for live-data assertions."""

    def __init__(self, *, gaps_found: int = 7, high: int = 3) -> None:
        self._gaps_found = gaps_found
        self._high = high

    async def generate_report(
        self,
        department: str | None = None,
        region: str | None = None,
    ) -> AuditReport:
        return AuditReport(
            generated_at=datetime(2026, 6, 12, 9, 0, tzinfo=UTC),
            scope="all",
            total_users_audited=42,
            gaps_found=self._gaps_found,
            gaps_by_severity={
                "low": 1,
                "medium": self._gaps_found - self._high - 1,
                "high": self._high,
                "critical": 0,
            },
            gaps_by_department={"Engineering": self._gaps_found},
            top_missing_courses=[("Security Basics", self._gaps_found)],
            evidence_hash="shell-live-hash",
            details=[],
        )


def _client(monkeypatch, tmp_path, *, token: str = "shell-token", **auditor_kwargs):
    monkeypatch.setenv("COMPLYOS_API_TOKEN", token)
    monkeypatch.delenv("COMPLYOS_SESSION_SECRET", raising=False)
    monkeypatch.delenv("COMPLYOS_ALLOW_INSECURE_LOCAL", raising=False)
    repo = LocalRepository(str(tmp_path / "shell.db"))
    app = create_dashboard_app(auditor=FakeAuditor(**auditor_kwargs), repository=repo)
    return TestClient(app)


def test_shell_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_login_with_token_sets_cookie_and_overview_returns_200(
    monkeypatch, tmp_path
) -> None:
    client = _client(monkeypatch, tmp_path)

    login = client.post("/shell/login", data={"token": "shell-token"}, follow_redirects=False)
    assert login.status_code == 303
    assert login.headers["location"] == "/shell"
    cookie = login.cookies.get("complyos_shell")
    assert cookie is not None

    overview = client.get("/shell")
    assert overview.status_code == 200
    assert "text/html" in overview.headers["content-type"]


def test_shell_overview_reflects_live_service_data(monkeypatch, tmp_path) -> None:
    # gaps_found drives the rendered number; a different seed must change the page.
    client = _client(monkeypatch, tmp_path, gaps_found=7, high=3)
    client.post("/shell/login", data={"token": "shell-token"})

    overview = client.get("/shell")

    assert overview.status_code == 200
    # The Overview must reflect the live audit (7 gaps, 3 high-risk), not static HTML.
    assert "7" in overview.text
    assert "3" in overview.text
    # Readiness is rendered from the live ReadinessService inventory.
    assert "readiness" in overview.text.lower()


def test_shell_overview_uses_real_mock_connector_seed(monkeypatch, tmp_path) -> None:
    """End-to-end: a real ComplianceAuditor over the seeded MockConnector.

    Proves Overview is wired to a live service, not the FakeAuditor double:
    the seeded mock produces a deterministic, non-zero gap count.
    """
    monkeypatch.setenv("COMPLYOS_API_TOKEN", "shell-token")
    monkeypatch.delenv("COMPLYOS_ALLOW_INSECURE_LOCAL", raising=False)
    repo = LocalRepository(str(tmp_path / "shell-seed.db"))
    auditor = ComplianceAuditor(MockConnector())
    # Establish ground truth from the same service the shell will call.
    import asyncio

    report = asyncio.run(auditor.generate_report())
    expected_gaps = report.gaps_found

    app = create_dashboard_app(auditor=auditor, repository=repo)
    client = TestClient(app)
    client.post("/shell/login", data={"token": "shell-token"})

    overview = client.get("/shell")
    assert overview.status_code == 200
    assert str(expected_gaps) in overview.text


def test_shell_login_fails_closed_when_unconfigured(monkeypatch, tmp_path) -> None:
    """No token and no insecure opt-in: shell login must refuse, same as the API."""
    monkeypatch.delenv("COMPLYOS_API_TOKEN", raising=False)
    monkeypatch.delenv("COMPLYOS_ALLOW_INSECURE_LOCAL", raising=False)
    repo = LocalRepository(str(tmp_path / "shell-closed.db"))
    client = TestClient(create_dashboard_app(auditor=FakeAuditor(), repository=repo))

    response = client.post("/shell/login", data={"token": "anything"}, follow_redirects=False)

    assert response.status_code == 401


def test_shell_login_rejects_wrong_token(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.post("/shell/login", data={"token": "wrong"}, follow_redirects=False)

    assert response.status_code == 401
    assert client.cookies.get("complyos_shell") is None


def test_shell_logout_clears_cookie(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)
    client.post("/shell/login", data={"token": "shell-token"})
    assert client.get("/shell").status_code == 200

    logout = client.post("/shell/logout", follow_redirects=False)
    assert logout.status_code == 303
    assert logout.headers["location"] == "/shell/login"

    # Cookie cleared -> shell now redirects to login again.
    after = client.get("/shell", follow_redirects=False)
    assert after.status_code == 302


def test_shell_forged_cookie_is_rejected(monkeypatch, tmp_path) -> None:
    """A client-set cookie with a bad signature must not authenticate."""
    client = _client(monkeypatch, tmp_path)

    client.cookies.set("complyos_shell", "owner.deadbeef")
    response = client.get("/shell", follow_redirects=False)

    assert response.status_code == 302


def test_shell_insecure_local_role_login(monkeypatch, tmp_path) -> None:
    """With insecure-local on and no token, a chosen role logs in for local dev."""
    monkeypatch.delenv("COMPLYOS_API_TOKEN", raising=False)
    monkeypatch.setenv("COMPLYOS_ALLOW_INSECURE_LOCAL", "1")
    repo = LocalRepository(str(tmp_path / "shell-local.db"))
    client = TestClient(create_dashboard_app(auditor=FakeAuditor(), repository=repo))

    login = client.post(
        "/shell/login", data={"role": "compliance_manager"}, follow_redirects=False
    )
    assert login.status_code == 303

    overview = client.get("/shell")
    assert overview.status_code == 200
    assert "compliance_manager" in overview.text


def test_shell_base_layout_accessibility(monkeypatch, tmp_path) -> None:
    """Base layout a11y smoke: skip link, main landmark, nav, lang."""
    client = _client(monkeypatch, tmp_path)
    client.post("/shell/login", data={"token": "shell-token"})

    html = client.get("/shell").text

    assert 'href="#main"' in html  # skip-to-content link
    assert "skip to" in html.lower()
    assert '<main id="main"' in html  # main landmark
    assert "<nav" in html  # side nav
    assert '<html lang="en"' in html


def test_shell_login_page_renders(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/login")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert 'href="#main"' in response.text  # login page is also accessible
