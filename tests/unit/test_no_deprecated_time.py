"""Regression checks for deprecated time APIs in project code."""

from __future__ import annotations

from pathlib import Path


def test_project_code_does_not_use_deprecated_utcnow() -> None:
    """Use the central UTC helper instead of ``datetime.utcnow()``."""

    project_root = Path(__file__).resolve().parents[2]
    offenders: list[str] = []
    for path in (project_root / "complyos").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "datetime.utcnow" in text:
            offenders.append(str(path.relative_to(project_root)))

    assert offenders == []
