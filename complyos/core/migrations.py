"""Small idempotent schema migration ledger.

This is intentionally not a full Alembic setup yet. It gives local/embedded
deployments a real migration ledger before the project graduates to managed
database migrations.
"""

from __future__ import annotations

from typing import Any, TypedDict

from sqlalchemy import text

SOURCE_INTEL_HARDENING_MIGRATION = "20260612_source_intel_hardening"
NOTIFICATION_OUTBOX_MIGRATION = "20260613_notification_outbox_hooks"


class SchemaMigration(TypedDict):
    migration_id: str
    description: str
    statements: list[str]


SCHEMA_MIGRATIONS: tuple[SchemaMigration, ...] = (
    {
        "migration_id": SOURCE_INTEL_HARDENING_MIGRATION,
        "description": "Source-intelligence schedules, job executions, and review packet ledger",
        "statements": [
            """
            CREATE TABLE IF NOT EXISTS source_intel_schedules (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL DEFAULT 'local-default',
                name VARCHAR NOT NULL,
                query VARCHAR NOT NULL,
                source_ids JSON NOT NULL DEFAULT '[]',
                interval_hours INTEGER NOT NULL DEFAULT 24,
                mode VARCHAR NOT NULL DEFAULT 'fixture',
                status VARCHAR NOT NULL DEFAULT 'active',
                created_by VARCHAR NOT NULL,
                last_run_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_source_intel_schedule_name UNIQUE (tenant_id, name)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS source_intel_job_executions (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL DEFAULT 'local-default',
                schedule_id VARCHAR NOT NULL,
                run_id VARCHAR,
                status VARCHAR NOT NULL,
                started_at DATETIME NOT NULL,
                finished_at DATETIME,
                summary JSON NOT NULL DEFAULT '{}',
                error VARCHAR,
                created_by VARCHAR NOT NULL
            )
            """,
        ],
    },
    {
        "migration_id": NOTIFICATION_OUTBOX_MIGRATION,
        "description": "Notification outbox events and retryable hook deliveries",
        "statements": [
            """
            CREATE TABLE IF NOT EXISTS notification_events (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL DEFAULT 'local-default',
                event_type VARCHAR NOT NULL,
                source VARCHAR NOT NULL DEFAULT 'complyos',
                object_type VARCHAR NOT NULL,
                object_id VARCHAR,
                payload JSON NOT NULL DEFAULT '{}',
                payload_hash VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'queued',
                created_by VARCHAR NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS notification_deliveries (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL DEFAULT 'local-default',
                event_id VARCHAR NOT NULL,
                channel VARCHAR NOT NULL,
                destination_ref VARCHAR NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                next_attempt_at DATETIME,
                last_error VARCHAR,
                response_metadata JSON NOT NULL DEFAULT '{}',
                sent_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ],
    },
)


def apply_schema_migrations(engine: Any) -> None:
    """Apply idempotent local schema migrations and record them in a ledger."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_id VARCHAR PRIMARY KEY,
                    description VARCHAR NOT NULL,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        applied = set(
            connection.execute(text("SELECT migration_id FROM schema_migrations")).scalars().all()
        )
        for migration in SCHEMA_MIGRATIONS:
            if migration["migration_id"] in applied:
                continue
            for statement in migration["statements"]:
                connection.execute(text(statement))
            connection.execute(
                text(
                    """
                    INSERT INTO schema_migrations (migration_id, description, applied_at)
                    VALUES (:migration_id, :description, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "migration_id": migration["migration_id"],
                    "description": migration["description"],
                },
            )


def list_applied_migrations(engine: Any) -> list[str]:
    """Return applied migration IDs for release/deploy diagnostics."""
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_id VARCHAR PRIMARY KEY,
                    description VARCHAR NOT NULL,
                    applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        return list(
            connection.execute(
                text("SELECT migration_id FROM schema_migrations ORDER BY applied_at, migration_id")
            )
            .scalars()
            .all()
        )
