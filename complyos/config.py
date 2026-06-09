"""Configuration management for ComplyOS."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATHS = [
    "complyos.yaml",
    "complyos.yml",
    os.path.expanduser("~/.complyos/config.yaml"),
    os.path.expanduser("~/.complyos/config.yml"),
]


class ComplyOSConfig:
    """Runtime configuration loaded from YAML files."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    @classmethod
    def load(cls, path: str | None = None) -> ComplyOSConfig:
        """Load config from the first available path."""
        paths = [path] if path else DEFAULT_CONFIG_PATHS
        for p in paths:
            if p and Path(p).exists():
                with open(p) as f:
                    return cls(yaml.safe_load(f) or {})
        return cls({})

    @property
    def connector(self) -> dict[str, Any]:
        return self._data.get("connector", {})

    @property
    def database(self) -> dict[str, Any]:
        return self._data.get("database", {})

    @property
    def defaults(self) -> dict[str, Any]:
        return self._data.get("defaults", {})

    @property
    def notification(self) -> dict[str, Any]:
        return self._data.get("notification", {})

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


def generate_config(
    connector_type: str = "mock",
    db_path: str = "complyos.db",
) -> str:
    """Generate a starter configuration file."""
    config = {
        "connector": {
            "type": connector_type,
            "workday": {
                "base_url": "${WORKDAY_BASE_URL}",
                "username": "${WORKDAY_USERNAME}",
                "password": "${WORKDAY_PASSWORD}",
            },
        },
        "database": {"path": db_path},
        "defaults": {
            "department": None,
            "region": None,
            "deadline_days": 30,
        },
        "notification": {
            "smtp_host": "${SMTP_HOST}",
            "smtp_port": 587,
            "smtp_username": "${SMTP_USERNAME}",
            "smtp_password": "${SMTP_PASSWORD}",
            "from_address": "complyos@example.com",
            "use_tls": True,
        },
    }
    return yaml.dump(config, default_flow_style=False, sort_keys=False)
