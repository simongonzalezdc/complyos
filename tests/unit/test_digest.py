"""Unit tests for the compliance digest engine."""

from __future__ import annotations

from datetime import datetime, timedelta

from complyos.connectors.mock import MockConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.digest import DigestEngine
from complyos.core.repository import LocalRepository
from complyos.models.domain import Enrollment, EnrollmentStatus


def make_engine(tmp_path, connector=None):
    connector = connector or MockConnector()
    repo = LocalRepository(str(tmp_path / "digest.db"))
    return DigestEngine(ComplianceAuditor(connector), repo), connector, repo


class TestDigestBaseline:
    async def test_first_run_is_baseline(self, tmp_path):
        engine, _, _ = make_engine(tmp_path)
        digest = await engine.generate()
        assert digest.trend == "baseline"
        assert digest.previous_gaps is None
        assert digest.previous_generated_at is None
        assert digest.new_gaps == []
        assert digest.resolved_gaps == []
        assert digest.current_gaps > 0
        assert digest.snapshot_id

    async def test_first_run_saves_snapshot(self, tmp_path):
        engine, _, repo = make_engine(tmp_path)
        digest = await engine.generate()
        snapshot = repo.get_latest_audit_snapshot(scope=digest.scope)
        assert snapshot is not None
        assert snapshot["id"] == digest.snapshot_id
        assert snapshot["gaps_found"] == digest.current_gaps


class TestDigestDiffing:
    async def test_flat_when_nothing_changes(self, tmp_path):
        engine, _, _ = make_engine(tmp_path)
        await engine.generate()
        second = await engine.generate()
        assert second.trend == "flat"
        assert second.new_gaps == []
        assert second.resolved_gaps == []
        assert second.previous_gaps == second.current_gaps

    async def test_improving_when_gap_resolved(self, tmp_path):
        engine, connector, _ = make_engine(tmp_path)
        first = await engine.generate()

        # Carol (u3) completes one of her missing mandatory courses
        connector.enrollments.append(
            Enrollment(
                id="e-new", user_id="u3", course_id="c1",
                status=EnrollmentStatus.COMPLETED,
                completed_date=datetime.now(),
            )
        )
        second = await engine.generate()
        assert second.trend == "improving"
        assert second.current_gaps == first.current_gaps - 1
        resolved_keys = {(e.user_id, e.course_code) for e in second.resolved_gaps}
        assert ("u3", "RESPECT-101") in resolved_keys
        assert second.new_gaps == []

    async def test_worsening_when_new_gap_appears(self, tmp_path):
        engine, connector, _ = make_engine(tmp_path)
        first = await engine.generate()

        # Alice's completed enrollment is revoked — she now misses c1 too
        connector.enrollments = [e for e in connector.enrollments if e.id != "e1"]
        second = await engine.generate()
        assert second.trend == "worsening"
        assert second.current_gaps == first.current_gaps + 1
        new_keys = {(e.user_id, e.course_code) for e in second.new_gaps}
        assert ("u1", "RESPECT-101") in new_keys

    async def test_scopes_are_independent(self, tmp_path):
        engine, _, _ = make_engine(tmp_path)
        all_scope = await engine.generate()
        dept_scope = await engine.generate(department="HR")
        assert all_scope.scope != dept_scope.scope
        # The department run must not inherit the all-scope baseline
        assert dept_scope.trend == "baseline"


class TestSnapshotRepository:
    async def test_latest_snapshot_wins(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "snap.db"))
        old = datetime.now() - timedelta(days=7)
        new = datetime.now()
        repo.save_audit_snapshot(
            scope="all", generated_at=old, gaps_found=5, gaps=[],
            gaps_by_severity={}, evidence_hash="old",
        )
        repo.save_audit_snapshot(
            scope="all", generated_at=new, gaps_found=3, gaps=[],
            gaps_by_severity={}, evidence_hash="new",
        )
        latest = repo.get_latest_audit_snapshot(scope="all")
        assert latest["evidence_hash"] == "new"
        assert len(repo.list_audit_snapshots(scope="all")) == 2

    async def test_clear_all_preserves_snapshots(self, tmp_path):
        repo = LocalRepository(str(tmp_path / "snap.db"))
        repo.save_audit_snapshot(
            scope="all", generated_at=datetime.now(), gaps_found=1, gaps=[],
            gaps_by_severity={}, evidence_hash="h",
        )
        repo.clear_all()
        assert repo.get_latest_audit_snapshot(scope="all") is not None
