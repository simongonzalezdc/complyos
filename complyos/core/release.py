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


def release_ready(root: Path | str = ".") -> bool:
    """Return True when every release check passes."""
    return all(item["ok"] for item in build_release_checklist(root))
