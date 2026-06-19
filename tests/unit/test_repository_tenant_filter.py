"""Repository defense-in-depth tenant filter tests (WP19).

The point-lookups ``get_import_batch``, ``list_import_rows``,
``get_privacy_request``, and ``get_legal_hold`` now accept an optional
``tenant_id`` keyword. When supplied, a row that exists but belongs to a
different tenant is hidden — defense in depth on top of the service-layer
post-fetch tenant check. The service layer is still the single authorization
choke-point; this layer just stops the repository from handing back a row
that the service will only reject after construction.
"""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.services.context import default_local_context
from complyos.services.imports import ImportPreviewRequest, ImportService
from complyos.services.privacy import PrivacyProgramService


def _seed_two_tenant_import_batches(tmp_path) -> tuple[str, str]:
    """Create one import batch per tenant; return the two batch ids."""
    repo = LocalRepository(str(tmp_path / "imports.db"))
    service = ImportService(repo)
    tenant_a = default_local_context(tenant_id="tenant-a", role="owner")
    tenant_b = default_local_context(tenant_id="tenant-b", role="owner")
    csv_payload = "user_id,course_id,status\nua-1,ca-1,completed\nub-1,cb-1,completed\n"
    preview_a = service.preview(
        tenant_a, ImportPreviewRequest(csv_text=csv_payload, source_system="a")
    )
    preview_b = service.preview(
        tenant_b, ImportPreviewRequest(csv_text=csv_payload, source_system="b")
    )
    return str(preview_a.batch_id), str(preview_b.batch_id)


def test_get_import_batch_returns_none_for_cross_tenant_request(tmp_path) -> None:
    """The repository hides a batch whose owner is a different tenant."""
    batch_a, batch_b = _seed_two_tenant_import_batches(tmp_path)
    repo = LocalRepository(str(tmp_path / "imports.db"))
    assert repo.get_import_batch(batch_a) is not None
    assert repo.get_import_batch(batch_a, tenant_id="tenant-a") is not None
    assert repo.get_import_batch(batch_a, tenant_id="tenant-b") is None
    assert repo.get_import_batch(batch_b, tenant_id="tenant-a") is None


def test_list_import_rows_returns_empty_for_cross_tenant_request(tmp_path) -> None:
    """Listing rows for a batch owned by another tenant returns no rows."""
    batch_a, _ = _seed_two_tenant_import_batches(tmp_path)
    repo = LocalRepository(str(tmp_path / "imports.db"))
    own = repo.list_import_rows(batch_a, tenant_id="tenant-a")
    assert own, "expected at least one row from tenant-a's batch"
    cross = repo.list_import_rows(batch_a, tenant_id="tenant-b")
    assert cross == []


def test_get_privacy_request_tenant_filter(tmp_path) -> None:
    """Cross-tenant privacy-request lookups return None."""
    repo = LocalRepository(str(tmp_path / "privacy.db"))
    service = PrivacyProgramService(repo)
    tenant_a = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    request = service.create_request(tenant_a, subject_id="u1", request_type="access")
    assert repo.get_privacy_request(str(request.request_id)) is not None
    assert repo.get_privacy_request(str(request.request_id), tenant_id="tenant-a") is not None
    assert repo.get_privacy_request(str(request.request_id), tenant_id="tenant-b") is None


def test_get_legal_hold_tenant_filter(tmp_path) -> None:
    """Cross-tenant legal-hold lookups return None."""
    repo = LocalRepository(str(tmp_path / "holds.db"))
    service = PrivacyProgramService(repo)
    tenant_a = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    hold = service.create_legal_hold(
        tenant_a, subject_id="s1", scope="subject", reason="litigation"
    )
    assert repo.get_legal_hold(str(hold.hold_id)) is not None
    assert repo.get_legal_hold(str(hold.hold_id), tenant_id="tenant-a") is not None
    assert repo.get_legal_hold(str(hold.hold_id), tenant_id="tenant-b") is None


def test_repository_filters_do_not_break_existing_callers(tmp_path) -> None:
    """The new keyword-only tenant_id is additive; old calls keep working."""
    batch_a, _ = _seed_two_tenant_import_batches(tmp_path)
    repo = LocalRepository(str(tmp_path / "imports.db"))
    # No tenant filter — original behavior preserved.
    assert repo.get_import_batch(batch_a) is not None
    assert repo.list_import_rows(batch_a)  # non-empty
    assert repo.get_legal_hold("missing") is None
