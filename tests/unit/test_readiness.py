"""Readiness service tests."""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.models.database import DBTenant
from complyos.services.context import default_local_context
from complyos.services.readiness import ReadinessService


def _seed_tenant(repo: LocalRepository) -> None:
    """Insert a tenant row with known data-governance metadata."""
    with repo._session() as session:
        session.add(
            DBTenant(
                id="acme",
                name="Acme School District",
                track_default="campus",
                status="active",
                data_region="us-west",
                processing_purpose="campus learning-compliance operations",
                data_categories=["student_learning_records", "staff_training"],
                retention_policy={"raw_import_days": 30, "evidence_days": 2555},
                subprocessor_profile={"email": "postmark", "storage": "s3-us-west"},
            )
        )
        session.commit()


def test_readiness_is_explicitly_readiness_only(tmp_path) -> None:
    service = ReadinessService(LocalRepository(str(tmp_path / "ready.db")))
    context = default_local_context(surface="cli")

    report = service.check(context)

    assert "readiness-only" in report.posture
    assert report.summary
    assert any(control.id == "gated-import-lifecycle" for control in report.controls)
    assert any(control.id == "hr-people-analytics-boundary" for control in report.controls)
    assert any("EEOC" in item for item in report.global_regulation_watchlist)
    assert "SOC 2 certified" in report.forbidden_claims


def test_readiness_surfaces_seeded_tenant_metadata(tmp_path) -> None:
    """Readiness includes the tenant's data-governance metadata (plan §15)."""
    repo = LocalRepository(str(tmp_path / "ready-meta.db"))
    _seed_tenant(repo)
    context = default_local_context(surface="cli", tenant_id="acme")

    report = ReadinessService(repo).check(context)

    meta = report.tenant_metadata
    assert meta.data_region == "us-west"
    assert meta.processing_purpose == "campus learning-compliance operations"
    assert meta.data_categories == ["student_learning_records", "staff_training"]
    assert meta.retention_policy == {"raw_import_days": 30, "evidence_days": 2555}
    assert meta.subprocessor_profile == {"email": "postmark", "storage": "s3-us-west"}


def test_readiness_tenant_metadata_empties_for_unseeded_tenant(tmp_path) -> None:
    """A tenant with no row yields sensible empties, never a crash."""
    repo = LocalRepository(str(tmp_path / "ready-empty.db"))
    context = default_local_context(surface="cli", tenant_id="no-such-tenant")

    meta = ReadinessService(repo).check(context).tenant_metadata

    assert meta.data_region is None
    assert meta.processing_purpose is None
    assert meta.data_categories == []
    assert meta.retention_policy == {}
    assert meta.subprocessor_profile == {}
