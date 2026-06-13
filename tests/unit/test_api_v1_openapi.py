"""OpenAPI presence test for the versioned API.

Rather than a brittle full-file snapshot, this asserts that the set of required
service-backed route groups is a subset of the generated OpenAPI paths. That is
robust to additive change (new routes never break it) while still catching the
accidental removal of any documented surface.
"""

from __future__ import annotations

from complyos.web.api_v1 import create_api_v1_app

# Every service-backed route group the API must expose, including the new
# admin/roles, sync, and plural-alias paths added in WP12.
REQUIRED_PATHS = frozenset(
    {
        # Audit / readiness
        "/api/v1/health",
        "/api/v1/readiness",
        "/api/v1/audits",
        "/api/v1/audit",
        "/api/v1/report",
        "/api/v1/digest",
        "/api/v1/learners/{user_id}/status",
        "/api/v1/users/{user_id}/status",
        # Connectors
        "/api/v1/connectors",
        "/api/v1/connectors/health",
        # Rules
        "/api/v1/rules/validate",
        "/api/v1/rules/preview",
        # Remediation
        "/api/v1/remediations",
        "/api/v1/remediate",
        # Imports
        "/api/v1/imports/preview",
        "/api/v1/imports/{batch_id}/decisions",
        "/api/v1/imports/{batch_id}/promote",
        # Evidence
        "/api/v1/evidence",
        "/api/v1/security/evidence",
        # Governance / source intel
        "/api/v1/governance/packet",
        "/api/v1/source-intel/proposals",
        # Privacy
        "/api/v1/privacy/requests",
        # Sync (WP12)
        "/api/v1/sync",
        # Admin role management (WP12)
        "/api/v1/admin/roles",
        "/api/v1/admin/roles/{actor_id}",
    }
)


def test_api_v1_openapi_exposes_required_route_groups() -> None:
    app = create_api_v1_app()
    paths = set(app.openapi()["paths"].keys())

    missing = REQUIRED_PATHS - paths
    assert not missing, f"OpenAPI is missing required routes: {sorted(missing)}"


def test_api_v1_openapi_admin_roles_supports_get_post_delete() -> None:
    app = create_api_v1_app()
    paths = app.openapi()["paths"]

    assert {"get", "post"} <= set(paths["/api/v1/admin/roles"].keys())
    assert "delete" in paths["/api/v1/admin/roles/{actor_id}"]


def test_api_v1_openapi_sync_is_post() -> None:
    app = create_api_v1_app()
    paths = app.openapi()["paths"]

    assert "post" in paths["/api/v1/sync"]
