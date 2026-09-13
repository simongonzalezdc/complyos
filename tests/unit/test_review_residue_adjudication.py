"""Adjudication tests for the 2026-09-01 post-merge review residue (item 47).

The two fl4write bot reviews (GitHub mirror PR #1 @ ebfb701a and PR #2 @
8e2b83f2 — both blob-identical to canonical main history via merge commits
e2474d5 / dcd11bb) alleged one Major and one Critical finding plus minors.
Most claims are already locked elsewhere; these tests pin the two claims
that had no direct proof, so the dispositions recorded in
reports/autonomy-plan-2026-09-12/glm-47-report.md stay re-runnable:

1. PR1 "Major — dashboard output_path path traversal": the described
   behavior (an actor-directed write outside the working directory) is
   real, and is the recorded design boundary from
   docs/enterprise-hardening-report.md (H6/WP13b): file-writing exports are
   CLI/MCP-only and permission-gated; the remote API returns content and
   never writes server disk (test_api_v1.py locks that half). These tests
   lock the MCP half: the default proposal-only role is denied fail-closed
   (even for a traversal-shaped relative path), and only an
   evidence:export-elevated role can direct the write — including outside
   the CWD, exactly as the bot alleged. If that boundary is ever tightened,
   these tests force the change to be conscious.

2. PR1 "Minor — DigestEngine saves a snapshot even when the audit fails":
   false on the current tree — an audit exception aborts the run before
   any snapshot is persisted.

All fixtures are synthetic (mock connector / generated CSV in tmp dirs);
no real customer records are involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from complyos.core.digest import DigestEngine
from complyos.core.repository import LocalRepository


class _ExplodingAuditor:
    """Stand-in auditor whose report generation always fails."""

    async def generate_report(self, **kwargs: object) -> None:
        raise RuntimeError("synthetic LMS outage")


class TestMcpDashboardExportBoundary:
    async def test_default_role_denied_fail_closed_even_for_traversal_path(
        self, monkeypatch, tmp_path
    ):
        from complyos.api.mcp_server import export_compliance_dashboard
        from complyos.services.context import AuthorizationError

        # Least-privileged default MCP role (agent_service_account) lacks
        # evidence:export; nothing may be written on denial.
        monkeypatch.delenv("COMPLYOS_MCP_ROLE", raising=False)
        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        with pytest.raises(AuthorizationError) as exc:
            await export_compliance_dashboard(
                output_path="../escaped-dashboard.html",
                db_path=str(tmp_path / "denied.db"),
            )

        assert exc.value.permission == "evidence:export"
        # Fail closed: the traversal-shaped target was not created.
        assert not (tmp_path / "escaped-dashboard.html").exists()

    async def test_elevated_role_can_direct_write_outside_cwd(
        self, monkeypatch, tmp_path
    ):
        from complyos.api.mcp_server import export_compliance_dashboard

        # The bot's literal claim — "output_path is user-controlled and
        # could write to arbitrary locations" — is TRUE for an
        # evidence:export-elevated MCP actor (here: a relative path that
        # escapes the working directory). File-writing exports are
        # deliberately CLI/MCP-only behind this permission (enterprise
        # hardening H6/WP13b); the remote API never writes server disk.
        monkeypatch.setenv("COMPLYOS_MCP_ROLE", "compliance_manager")
        workdir = tmp_path / "work"
        workdir.mkdir()
        monkeypatch.chdir(workdir)

        result = await export_compliance_dashboard(
            output_path="../escaped-dashboard.html",
            db_path=str(tmp_path / "dash.db"),
        )

        target = tmp_path / "escaped-dashboard.html"
        assert Path(result["dashboard_path"]).resolve() == target.resolve()
        assert target.exists()
        assert target.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")


class TestDigestFailurePersistence:
    async def test_failed_audit_persists_no_snapshot(self, tmp_path):
        # Disproves the review claim that a digest run "saves a snapshot
        # even when the audit fails": the report generation happens first
        # and its exception aborts the run before save_audit_snapshot.
        repo = LocalRepository(str(tmp_path / "digest.db"))
        engine = DigestEngine(_ExplodingAuditor(), repo)  # type: ignore[arg-type]

        with pytest.raises(RuntimeError, match="synthetic LMS outage"):
            await engine.generate()

        assert repo.list_audit_snapshots() == []
        assert repo.get_latest_audit_snapshot(scope="all") is None
