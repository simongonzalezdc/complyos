"""Operator release-readiness checks."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict


class ReleaseCheck(TypedDict):
    id: str
    label: str
    ok: bool
    message: str


def _file_contains(root: Path, relative_path: str, required: str | None = None) -> bool:
    path = root / relative_path
    if not path.exists():
        return False
    if required is None:
        return True
    return required.lower() in path.read_text(encoding="utf-8").lower()


def build_release_checklist(root: Path | str = ".") -> list[ReleaseCheck]:
    """Return release-readiness checks for operator-facing releases."""
    base = Path(root)
    checks: list[ReleaseCheck] = []

    required_files = [
        ("license", "License", "LICENSE", "Business Source License 1.1"),
        ("security_policy", "Security policy", "SECURITY.md", None),
        ("readme", "README", "README.md", "Roadmap"),
        ("architecture", "Architecture", "ARCHITECTURE.md", "Roadmap"),
        ("landing_page", "Landing page", "docs/index.html", "ComplyOS"),
        (
            "release_checklist",
            "Release checklist",
            "docs/release-checklist.md",
            "Release checklist",
        ),
    ]

    for check_id, label, relative_path, required_text in required_files:
        ok = _file_contains(base, relative_path, required_text)
        message = (
            f"{relative_path} present"
            if ok
            else f"{relative_path} missing or does not contain required release text"
        )
        checks.append({"id": check_id, "label": label, "ok": ok, "message": message})

    return checks


def build_deployment_checklist(root: Path | str = ".") -> list[ReleaseCheck]:
    """Return deployment hardening checks for source-intelligence operations."""
    base = Path(root)
    checks = build_release_checklist(base)
    deployment_checks = [
        (
            "source_intel_docs",
            "Source intelligence hardening docs",
            "docs/source-intelligence-engine-v0.md",
            "production hardening",
        ),
        (
            "external_api_list",
            "External API research list",
            "docs/external-api-research-list.md",
            "list-only",
        ),
        (
            "source_intel_review_ui",
            "Source intelligence review UI",
            "complyos/web/dashboard.py",
            "/source-intel/review",
        ),
        (
            "source_intel_api_endpoints",
            "Source intelligence API endpoints",
            "complyos/web/api_v1.py",
            "/source-intel/export-packet",
        ),
        (
            "migration_strategy",
            "Schema migration strategy",
            "complyos/core/migrations.py",
            "20260612_source_intel_hardening",
        ),
        (
            "observability_action_logs",
            "Source intelligence action logging",
            "complyos/services/source_intel.py",
            "source_intel.schedule.execute",
        ),
    ]
    for check_id, label, relative_path, required_text in deployment_checks:
        ok = _file_contains(base, relative_path, required_text)
        message = (
            f"{relative_path} contains {required_text}"
            if ok
            else f"{relative_path} missing required deployment text: {required_text}"
        )
        checks.append({"id": check_id, "label": label, "ok": ok, "message": message})
    return checks


def release_ready(root: Path | str = ".") -> bool:
    """Return True when every release check passes."""
    return all(item["ok"] for item in build_release_checklist(root))
