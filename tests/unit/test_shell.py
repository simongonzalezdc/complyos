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


def test_shell_session_cookie_not_secure_by_default(monkeypatch, tmp_path) -> None:
    """Local-first default serves over HTTP, so the cookie is not marked Secure."""
    monkeypatch.delenv("COMPLYOS_SESSION_SECURE", raising=False)
    client = _client(monkeypatch, tmp_path)

    login = client.post("/shell/login", data={"token": "shell-token"}, follow_redirects=False)

    set_cookie = login.headers["set-cookie"]
    assert "complyos_shell=" in set_cookie
    assert "Secure" not in set_cookie


def test_shell_session_cookie_secure_when_flag_set(monkeypatch, tmp_path) -> None:
    """With COMPLYOS_SESSION_SECURE set, the session cookie carries Secure."""
    monkeypatch.setenv("COMPLYOS_SESSION_SECURE", "1")
    client = _client(monkeypatch, tmp_path)

    login = client.post("/shell/login", data={"token": "shell-token"}, follow_redirects=False)

    set_cookie = login.headers["set-cookie"]
    assert "complyos_shell=" in set_cookie
    assert "Secure" in set_cookie


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


# ---------------------------------------------------------------------------
# WP16b — three live modules: Gaps, Imports, Evidence.
# ---------------------------------------------------------------------------


def _local_client(monkeypatch, tmp_path, db_name: str):
    """Insecure-local shell client (no token) over a real MockConnector auditor.

    Insecure-local mode lets a test pick a low-privilege role at login, which is
    how the permission-panel degradation paths are exercised below.
    """
    monkeypatch.delenv("COMPLYOS_API_TOKEN", raising=False)
    monkeypatch.setenv("COMPLYOS_ALLOW_INSECURE_LOCAL", "1")
    repo = LocalRepository(str(tmp_path / db_name))
    auditor = ComplianceAuditor(MockConnector())
    app = create_dashboard_app(auditor=auditor, repository=repo)
    return TestClient(app), repo


def _login_local(client: TestClient, role: str) -> None:
    # Don't follow the redirect to Overview: low-privilege roles (e.g. importer)
    # may lack readiness:read, which the Overview module requires. The cookie is
    # set on the 303 response itself, so the module routes under test still see
    # an authenticated context.
    client.post("/shell/login", data={"role": role}, follow_redirects=False)


# ---- Gaps -----------------------------------------------------------------


def test_shell_gaps_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/gaps", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_gaps_renders_live_audit_data(monkeypatch, tmp_path) -> None:
    """The gap queue must reflect the live AuditService over the seeded mock.

    MockConnector deterministically produces a gap for user ``u1`` in
    Engineering missing the "Information Security Basics" course — assert those
    seeded values appear in the rendered table, proving live data.
    """
    client, _ = _local_client(monkeypatch, tmp_path, "shell-gaps.db")
    _login_local(client, "compliance_manager")

    response = client.get("/shell/gaps")

    assert response.status_code == 200
    assert "u1" in response.text
    assert "Engineering" in response.text
    assert "Information Security Basics" in response.text


def test_shell_gaps_severity_filter_is_server_side(monkeypatch, tmp_path) -> None:
    """An unmatched severity filter empties the live queue server-side."""
    client, _ = _local_client(monkeypatch, tmp_path, "shell-gaps-filter.db")
    _login_local(client, "compliance_manager")

    # The mock seed yields only medium-severity gaps; filtering to high removes
    # the u1 row entirely, proving the filter runs server-side over live data.
    response = client.get("/shell/gaps?severity=high")

    assert response.status_code == 200
    assert "u1" not in response.text


def test_shell_gaps_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking audit:run gets the inline permission panel, not a 500."""
    client, _ = _local_client(monkeypatch, tmp_path, "shell-gaps-perm.db")
    # read_only has audit:read but NOT audit:run (the gap queue runs an audit).
    _login_local(client, "read_only")

    response = client.get("/shell/gaps")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "audit:run" in response.text


# ---- Imports --------------------------------------------------------------


def test_shell_imports_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/imports", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_imports_get_renders_paste_form(monkeypatch, tmp_path) -> None:
    client, _ = _local_client(monkeypatch, tmp_path, "shell-imports.db")
    _login_local(client, "importer")

    response = client.get("/shell/imports")

    assert response.status_code == 200
    assert "csv_text" in response.text  # the paste field
    assert 'action="/shell/imports/preview"' in response.text


def test_shell_imports_preview_reflects_pasted_csv(monkeypatch, tmp_path) -> None:
    """Preview POST renders a table driven by the pasted CSV (live ImportService).

    The CSV has 2 rows and an unexpected ``completed_at`` column; the preview
    must surface the row count, the unexpected column, and the
    ``UNEXPECTED_COLUMN`` issue — none of which are static.
    """
    client, _ = _local_client(monkeypatch, tmp_path, "shell-imports-preview.db")
    _login_local(client, "importer")

    csv_text = (
        "user_id,course_id,status,completed_at\n"
        "u1,c1,completed,2026-01-15\n"
        "u2,c2,bogusstatus,notadate\n"
    )
    response = client.post("/shell/imports/preview", data={"csv_text": csv_text})

    assert response.status_code == 200
    assert "completed_at" in response.text  # the unexpected column
    assert "UNEXPECTED_COLUMN" in response.text  # the live issue code
    assert "NEEDS_DECISION" in response.text  # the live row-status bucket


def test_shell_imports_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking import:preview gets the inline permission panel on preview."""
    client, _ = _local_client(monkeypatch, tmp_path, "shell-imports-perm.db")
    # read_only lacks import:preview.
    _login_local(client, "read_only")

    response = client.post(
        "/shell/imports/preview", data={"csv_text": "user_id\nu1\n"}
    )

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "import:preview" in response.text


# ---- Evidence -------------------------------------------------------------


def test_shell_evidence_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/evidence", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_evidence_renders_seeded_ledger_entry(monkeypatch, tmp_path) -> None:
    """The evidence ledger table reflects a seeded entry (live repository read)."""
    client, repo = _local_client(monkeypatch, tmp_path, "shell-evidence.db")
    # Seed a ledger entry for the default tenant the shell context carries.
    repo.append_evidence_entry(
        tenant_id="local-default",
        query_type="audit_gaps",
        query_params={"department": "Engineering"},
        raw_data_hash="raw-seed-abc",
        transformation_steps=["normalize", "match-rules"],
        output_hash="evidence-seed-deadbeef",
        output_summary="4 gaps across 5 workers",
    )
    _login_local(client, "compliance_manager")

    response = client.get("/shell/evidence")

    assert response.status_code == 200
    assert "evidence-seed-deadbeef" in response.text  # the seeded evidence hash
    assert "audit_gaps" in response.text  # the seeded query/action type
    assert "4 gaps across 5 workers" in response.text  # the seeded summary


def test_shell_evidence_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking evidence:read gets the inline permission panel, not a 500.

    No built-in insecure-local role lacks evidence:read, so register a minimal
    restricted role for the duration of the test. The shell verifies the role
    against ROLE_PERMISSIONS and rebuilds the context from the same table, so a
    role with no evidence:read flows end-to-end and the service raises.
    """
    from complyos.services import context as ctx_module

    restricted = "no_evidence_role"
    monkeypatch.setitem(
        ctx_module.ROLE_PERMISSIONS, restricted, frozenset({"readiness:read"})
    )
    client, _ = _local_client(monkeypatch, tmp_path, "shell-evidence-perm.db")
    _login_local(client, restricted)

    response = client.get("/shell/evidence")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "evidence:read" in response.text


# ---- Overview degrades for low-privilege roles (regression) ----------------


def test_shell_overview_does_not_500_for_role_lacking_readiness(
    monkeypatch, tmp_path
) -> None:
    """A logged-in role without readiness:read must still get the Overview.

    Regression: the Overview's ReadinessService.check() used to run outside any
    try/except, so an importer (no readiness:read) 500'd on the landing page.
    The readiness tile now degrades to "restricted" instead of crashing.
    """
    client, _ = _local_client(monkeypatch, tmp_path, "shell-overview-lowpriv.db")
    _login_local(client, "importer")

    response = client.get("/shell")

    assert response.status_code == 200
    assert "restricted" in response.text.lower()


# ---------------------------------------------------------------------------
# WP16c — Remediation, Source-intel, Privacy, Readiness, Admin + import
# decide/promote.
# ---------------------------------------------------------------------------


# ---- Remediation ----------------------------------------------------------


def test_shell_remediation_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/remediation", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_remediation_renders_live_dry_run_proposal(monkeypatch, tmp_path) -> None:
    """The remediation queue is the live dry-run proposal over the seeded mock.

    The MockConnector seed yields a gap for user ``u1``; with auto_remind on,
    RemediationService.propose proposes a ``reminder`` action for ``u1`` — assert
    both appear, proving live (not static) data, and a dry-run that sent nothing.
    """
    client, _ = _local_client(monkeypatch, tmp_path, "shell-remediation.db")
    _login_local(client, "compliance_manager")

    response = client.get("/shell/remediation")

    assert response.status_code == 200
    assert "u1" in response.text
    assert "reminder" in response.text
    # Execution must be labeled as requiring approval, never a default control.
    assert "requires approval" in response.text.lower()


def test_shell_remediation_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking remediation:propose gets the inline permission panel."""
    client, _ = _local_client(monkeypatch, tmp_path, "shell-remediation-perm.db")
    # read_only lacks remediation:propose.
    _login_local(client, "read_only")

    response = client.get("/shell/remediation")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "remediation:propose" in response.text


# ---- Source intelligence --------------------------------------------------


def _seed_source_intel_proposal(repo) -> str:
    """Seed one source-intelligence proposal for the shell's default tenant.

    Builds a real SourceMonitorRun through the regwatch/microlearning adapters
    and persists it via the service, so the shell reads a live proposal.
    """
    from complyos.microlearning import MicrolearningAdapter
    from complyos.regwatch import RegWatchAdapter
    from complyos.services.context import default_local_context
    from complyos.services.source_intel import SourceIntelService
    from complyos.source_intel import (
        SourceDefinition,
        SourceIntelEngine,
        SourceSnapshot,
        SourceType,
    )
    from complyos.source_intel.monitor import SourceMonitorRun

    source = SourceDefinition(
        id="seed-source",
        name="Seed Source",
        url="https://example.gov/seed-rule",
        source_type=SourceType.OFFICIAL_REGULATOR,
        authority="official",
        jurisdictions=["US"],
        topics=["safety training"],
    )
    snapshot = SourceSnapshot.from_text(
        source_id=source.id,
        url=source.url,
        title="Final rule on worker training",
        text="A final rule says covered employers must train workers on safety.",
    )
    proposals = SourceIntelEngine(
        adapters=[RegWatchAdapter(), MicrolearningAdapter()]
    ).evaluate([source], [snapshot])
    run = SourceMonitorRun(
        source_count=1,
        snapshot_count=1,
        proposal_count=len(proposals),
        proposals=proposals,
        coverage_gaps=[],
    )
    context = default_local_context(
        surface="shell", role="compliance_manager", tenant_id="local-default"
    )
    SourceIntelService(repo).record_run(context, query="training", run=run)
    return source.id


def test_shell_source_intel_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/source-intel", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_source_intel_renders_seeded_proposal(monkeypatch, tmp_path) -> None:
    """The signal queue reflects a seeded proposal (live repository read)."""
    client, repo = _local_client(monkeypatch, tmp_path, "shell-source-intel.db")
    seeded_source_id = _seed_source_intel_proposal(repo)
    _login_local(client, "compliance_manager")

    response = client.get("/shell/source-intel")

    assert response.status_code == 200
    assert seeded_source_id in response.text  # the seeded source id
    assert "regulatory_change" in response.text  # a live seeded signal type


def test_shell_source_intel_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking source_intel:read gets the inline permission panel."""
    from complyos.services import context as ctx_module

    restricted = "no_source_intel_role"
    monkeypatch.setitem(
        ctx_module.ROLE_PERMISSIONS, restricted, frozenset({"readiness:read"})
    )
    client, _ = _local_client(monkeypatch, tmp_path, "shell-source-intel-perm.db")
    _login_local(client, restricted)

    response = client.get("/shell/source-intel")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "source_intel:read" in response.text


# ---- Privacy & retention --------------------------------------------------


def _seed_privacy_posture(repo) -> str:
    """Seed an active legal hold + retention policy for the default tenant."""
    from complyos.services.context import default_local_context
    from complyos.services.privacy import PrivacyProgramService

    context = default_local_context(
        surface="shell", role="privacy_admin", tenant_id="local-default"
    )
    service = PrivacyProgramService(repo)
    hold = service.create_legal_hold(
        context,
        subject_id="subject-seed-1",
        scope="subject",
        reason="seed-litigation-hold",
    )
    service.configure_retention_policy(
        context,
        raw_import_days=30,
        evidence_days=2555,
        action_log_days=2555,
        ai_proposal_days=180,
    )
    return hold.hold_id


def test_shell_privacy_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/privacy", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_privacy_renders_seeded_hold_and_policy(monkeypatch, tmp_path) -> None:
    """The privacy posture surfaces a seeded legal hold and retention policy.

    Read-only by construction: the GET reads list_active_legal_holds and
    get_retention_policy and never calls a mutating export/delete method.
    """
    client, repo = _local_client(monkeypatch, tmp_path, "shell-privacy.db")
    seeded_hold_id = _seed_privacy_posture(repo)
    _login_local(client, "privacy_admin")

    response = client.get("/shell/privacy")

    assert response.status_code == 200
    assert seeded_hold_id in response.text  # the seeded legal hold
    assert "seed-litigation-hold" in response.text  # the seeded hold reason
    assert "raw_import_days" in response.text  # the seeded retention policy key


def test_shell_privacy_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking privacy:request gets the inline permission panel."""
    client, _ = _local_client(monkeypatch, tmp_path, "shell-privacy-perm.db")
    # read_only lacks privacy:request.
    _login_local(client, "read_only")

    response = client.get("/shell/privacy")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "privacy:request" in response.text


# ---- Readiness ------------------------------------------------------------


def test_shell_readiness_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/readiness", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_readiness_renders_live_control_matrix(monkeypatch, tmp_path) -> None:
    """The readiness matrix reflects the live ReadinessService control inventory.

    The service always emits the ``access-control-service-authz`` control with a
    ``designed`` status — assert a control title and a status chip appear, proving
    the matrix is rendered from live data.
    """
    client, _ = _local_client(monkeypatch, tmp_path, "shell-readiness.db")
    _login_local(client, "compliance_manager")

    response = client.get("/shell/readiness")

    assert response.status_code == 200
    assert "Service-layer actor context and permissions" in response.text
    assert "designed" in response.text


def test_shell_readiness_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking readiness:read gets the inline permission panel."""
    client, _ = _local_client(monkeypatch, tmp_path, "shell-readiness-perm.db")
    # importer lacks readiness:read.
    _login_local(client, "importer")

    response = client.get("/shell/readiness")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "readiness:read" in response.text


# ---- Administration -------------------------------------------------------


def test_shell_admin_unauthenticated_redirects_to_login(monkeypatch, tmp_path) -> None:
    client = _client(monkeypatch, tmp_path)

    response = client.get("/shell/admin", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/shell/login"


def test_shell_admin_renders_seeded_role_binding(monkeypatch, tmp_path) -> None:
    """The role-bindings table reflects a seeded binding (live repository read)."""
    from complyos.services.context import default_local_context
    from complyos.services.role_admin import RoleAdminService

    client, repo = _local_client(monkeypatch, tmp_path, "shell-admin.db")
    context = default_local_context(surface="shell", role="owner", tenant_id="local-default")
    RoleAdminService(repo).set_role_binding(
        context, actor_id="seed-actor-42", role="reviewer"
    )
    _login_local(client, "owner")

    response = client.get("/shell/admin")

    assert response.status_code == 200
    assert "seed-actor-42" in response.text  # the seeded actor
    assert "reviewer" in response.text  # the seeded role


def test_shell_admin_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking admin:manage gets the inline permission panel.

    Only ``owner`` carries admin:manage in the catalog, so even ``admin`` (which
    holds everything except admin:manage) is denied here.
    """
    client, _ = _local_client(monkeypatch, tmp_path, "shell-admin-perm.db")
    _login_local(client, "admin")

    response = client.get("/shell/admin")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "admin:manage" in response.text


# ---- Imports decide/promote (deferred from WP16b) -------------------------


def _seed_import_batch(repo, *, csv_text: str) -> str:
    """Preview a CSV through the live service and return the new batch id."""
    from complyos.services.context import default_local_context
    from complyos.services.imports import ImportPreviewRequest, ImportService

    context = default_local_context(
        surface="shell", role="import_approver", tenant_id="local-default"
    )
    result = ImportService(repo).preview(context, ImportPreviewRequest(csv_text=csv_text))
    return result.batch_id


def test_shell_imports_decide_then_promote_succeeds(monkeypatch, tmp_path) -> None:
    """Accepting a NEEDS_DECISION row then promoting moves the batch to PROMOTED.

    The seeded CSV has a duplicate row, which the live service routes to
    NEEDS_DECISION (blocking). Promotion is fail-closed until the row is accepted;
    after accepting, promote succeeds and the batch reports PROMOTED.
    """
    client, repo = _local_client(monkeypatch, tmp_path, "shell-imports-decide.db")
    # Duplicate (u1,c1) rows -> the second is DUPLICATE_ROW -> NEEDS_DECISION.
    csv_text = "user_id,course_id\nu1,c1\nu1,c1\n"
    batch_id = _seed_import_batch(repo, csv_text=csv_text)
    _login_local(client, "import_approver")

    # Fail-closed: promoting a batch with a NEEDS_DECISION row stays QUARANTINED.
    blocked = client.post(f"/shell/imports/{batch_id}/promote")
    assert blocked.status_code == 200
    assert "QUARANTINED" in blocked.text

    rows = repo.list_import_rows(batch_id)
    needs_decision = next(r for r in rows if r["validation_status"] == "NEEDS_DECISION")

    accepted = client.post(
        f"/shell/imports/{batch_id}/decisions",
        data={"row_id": needs_decision["id"], "decision_type": "accept"},
    )
    assert accepted.status_code == 200

    promoted = client.post(f"/shell/imports/{batch_id}/promote")
    assert promoted.status_code == 200
    assert "PROMOTED" in promoted.text
    assert repo.get_import_batch(batch_id)["status"] == "PROMOTED"


def test_shell_imports_promote_blocked_batch_stays_quarantined(monkeypatch, tmp_path) -> None:
    """A batch with a rejected (blocking) row can never be promoted from the shell."""
    client, repo = _local_client(monkeypatch, tmp_path, "shell-imports-blocked.db")
    # A row missing course_id is a blocker -> REJECTED -> promotion blocked.
    csv_text = "user_id,course_id\nu1,\n"
    batch_id = _seed_import_batch(repo, csv_text=csv_text)
    _login_local(client, "import_approver")

    promoted = client.post(f"/shell/imports/{batch_id}/promote")

    assert promoted.status_code == 200
    assert "QUARANTINED" in promoted.text
    assert repo.get_import_batch(batch_id)["status"] == "QUARANTINED"


def test_shell_imports_decide_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking import:decide gets the inline permission panel on decide."""
    client, repo = _local_client(monkeypatch, tmp_path, "shell-imports-decide-perm.db")
    csv_text = "user_id,course_id\nu1,c1\nu1,c1\n"
    batch_id = _seed_import_batch(repo, csv_text=csv_text)
    rows = repo.list_import_rows(batch_id)
    needs_decision = next(r for r in rows if r["validation_status"] == "NEEDS_DECISION")
    # read_only lacks import:decide.
    _login_local(client, "read_only")

    response = client.post(
        f"/shell/imports/{batch_id}/decisions",
        data={"row_id": needs_decision["id"], "decision_type": "accept"},
    )

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "import:decide" in response.text


def test_shell_imports_promote_permission_panel_for_low_priv_role(monkeypatch, tmp_path) -> None:
    """A role lacking import:promote gets the inline permission panel on promote."""
    client, repo = _local_client(monkeypatch, tmp_path, "shell-imports-promote-perm.db")
    csv_text = "user_id,course_id\nu1,c1\n"
    batch_id = _seed_import_batch(repo, csv_text=csv_text)
    # importer has import:decide/preview but NOT import:promote.
    _login_local(client, "importer")

    response = client.post(f"/shell/imports/{batch_id}/promote")

    assert response.status_code == 200
    assert "do not have permission" in response.text.lower()
    assert "import:promote" in response.text
