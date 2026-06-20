"""Configuration management for ComplyOS."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")

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

    def database_path(self, default: str = "complyos.db") -> str:
        """Return the configured SQLite database path or a fallback."""
        path = self.database.get("path")
        return str(path) if path else default


def resolve_env_placeholder(value: Any) -> Any:
    """Resolve a ${VAR} config placeholder while leaving ordinary values intact."""
    if not isinstance(value, str):
        return value
    match = _ENV_PLACEHOLDER_RE.match(value.strip())
    if match:
        return os.getenv(match.group(1))
    return value


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
            "successfactors": {
                "base_url": "${SUCCESSFACTORS_BASE_URL}",
                "client_id": "${SUCCESSFACTORS_CLIENT_ID}",
                "client_secret": "${SUCCESSFACTORS_CLIENT_SECRET}",
                "company_id": "${SUCCESSFACTORS_COMPANY_ID}",
                "user_id": "${SUCCESSFACTORS_USER_ID}",
            },
            "cornerstone": {
                "base_url": "${CORNERSTONE_BASE_URL}",
                "client_id": "${CORNERSTONE_CLIENT_ID}",
                "client_secret": "${CORNERSTONE_CLIENT_SECRET}",
            },
            "canvas": {
                "base_url": "${CANVAS_BASE_URL}",
                "api_token": "${CANVAS_API_TOKEN}",
                "course_id": "${CANVAS_COURSE_ID}",
                "account_id": "${CANVAS_ACCOUNT_ID}",
            },
            "brightspace": {
                "base_url": "${BRIGHTSPACE_BASE_URL}",
                "client_id": "${BRIGHTSPACE_CLIENT_ID}",
                "client_secret": "${BRIGHTSPACE_CLIENT_SECRET}",
                "token_url": "${BRIGHTSPACE_TOKEN_URL}",
                "org_unit_id": "${BRIGHTSPACE_ORG_UNIT_ID}",
            },
            "moodle": {
                "base_url": "${MOODLE_BASE_URL}",
                "token": "${MOODLE_TOKEN}",
                "course_id": "${MOODLE_COURSE_ID}",
            },
            "blackboard": {
                "base_url": "${BLACKBOARD_BASE_URL}",
                "client_id": "${BLACKBOARD_CLIENT_ID}",
                "client_secret": "${BLACKBOARD_CLIENT_SECRET}",
                "course_id": "${BLACKBOARD_COURSE_ID}",
            },
        },
        "ai": {
            # Proposal-only AI content provider. Default ``deterministic`` keeps
            # the deterministic rules (no network, no model). Set ``local`` to
            # route content through an OpenAI-compatible local runtime (Ollama,
            # llama.cpp, vLLM, LM Studio). Redaction, hashing/provenance,
            # persistence, and the approve/reject lifecycle stay owned by the
            # service regardless of provider; a model outage falls back to
            # deterministic and never raises to the caller.
            "provider": "${COMPLYOS_AI_PROVIDER}",
            "base_url": "${COMPLYOS_AI_BASE_URL}",
            "model": "${COMPLYOS_AI_MODEL}",
            "timeout_seconds": "${COMPLYOS_AI_TIMEOUT_SECONDS}",
            "api_key": "${COMPLYOS_AI_API_KEY}",
            # Opt-in (default off). Truthy appends the ``/no_think`` soft-switch to
            # the outbound prompt so "thinking"/reasoning models (Qwen3/3.5,
            # DeepSeek-R1 distills) skip reasoning. Off = behavior unchanged.
            "disable_thinking": "${COMPLYOS_AI_DISABLE_THINKING}",
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
            "slack_webhook_url": "${SLACK_WEBHOOK_URL}",
            "teams_webhook_url": "${TEAMS_WEBHOOK_URL}",
        },
        "schedule": {
            "jobs": [
                {
                    "name": "daily-all",
                    "interval_hours": 24,
                    "department": None,
                    "region": None,
                    "dashboard_path": "reports/complyos-dashboard.html",
                }
            ],
        },
    }
    return yaml.dump(config, default_flow_style=False, sort_keys=False)
