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
NOTIFICATION_PREFERENCES_MIGRATION = "20260613_notification_preferences"
INBOUND_WEBHOOKS_MIGRATION = "20260613_inbound_webhook_events"
PERFORMANCE_INDEXES_MIGRATION = "20260614_performance_indexes"


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
    {
        "migration_id": NOTIFICATION_PREFERENCES_MIGRATION,
        "description": "Tenant notification channel preferences and kill switches",
        "statements": [
            """
            CREATE TABLE IF NOT EXISTS notification_preferences (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL DEFAULT 'local-default',
                channel VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL DEFAULT '*',
                enabled BOOLEAN NOT NULL DEFAULT 1,
                reason VARCHAR,
                updated_by VARCHAR NOT NULL,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_notification_preference_scope UNIQUE (
                    tenant_id,
                    channel,
                    event_type
                )
            )
            """,
        ],
    },
    {
        "migration_id": INBOUND_WEBHOOKS_MIGRATION,
        "description": "Generic inbound webhook receipt ledger",
        "statements": [
            """
            CREATE TABLE IF NOT EXISTS inbound_webhook_events (
                id VARCHAR PRIMARY KEY,
                tenant_id VARCHAR NOT NULL DEFAULT 'local-default',
                source VARCHAR NOT NULL,
                event_type VARCHAR NOT NULL,
                object_type VARCHAR NOT NULL DEFAULT 'inbound_event',
                object_id VARCHAR,
                payload JSON NOT NULL DEFAULT '{}',
                payload_hash VARCHAR NOT NULL,
                signature_valid BOOLEAN NOT NULL DEFAULT 0,
                status VARCHAR NOT NULL DEFAULT 'received',
                header_metadata JSON NOT NULL DEFAULT '{}',
                received_by VARCHAR NOT NULL,
                received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
        ],
    },
    {
        "migration_id": PERFORMANCE_INDEXES_MIGRATION,
        "description": "Indexes on hot tenant/subject/foreign-key/status filter columns",
        "statements": [
            # Foreign-key columns scanned on every DSR export/delete and audit run.
            "CREATE INDEX IF NOT EXISTS ix_enrollments_user_id ON enrollments (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_enrollments_course_id ON enrollments (course_id)",
            "CREATE INDEX IF NOT EXISTS ix_learning_records_user_id "
            "ON learning_records (user_id)",
            "CREATE INDEX IF NOT EXISTS ix_learning_records_course_id "
            "ON learning_records (course_id)",
            # Tenant-scoped append-only audit tables (grow without bound until retention).
            "CREATE INDEX IF NOT EXISTS ix_evidence_ledger_tenant_id "
            "ON evidence_ledger (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_audit_action_logs_tenant_id "
            "ON audit_action_logs (tenant_id)",
            # Import lifecycle lookups by batch and tenant/status.
            "CREATE INDEX IF NOT EXISTS ix_import_batches_tenant_status "
            "ON import_batches (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_import_rows_batch_id ON import_rows (batch_id)",
            "CREATE INDEX IF NOT EXISTS ix_import_decisions_batch_id "
            "ON import_decisions (batch_id)",
            # AI proposals and privacy program retention scans.
            "CREATE INDEX IF NOT EXISTS ix_ai_proposals_tenant_status "
            "ON ai_proposals (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_privacy_requests_tenant_status "
            "ON privacy_requests (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_legal_holds_tenant_status "
            "ON legal_holds (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_legal_holds_subject_id ON legal_holds (subject_id)",
            # Notification outbox drain and source-intel review queues.
            "CREATE INDEX IF NOT EXISTS ix_notification_events_tenant_status "
            "ON notification_events (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_tenant_status "
            "ON notification_deliveries (tenant_id, status)",
            "CREATE INDEX IF NOT EXISTS ix_notification_deliveries_event_id "
            "ON notification_deliveries (event_id)",
            "CREATE INDEX IF NOT EXISTS ix_source_intel_proposals_tenant_id "
            "ON source_intel_proposals (tenant_id)",
            "CREATE INDEX IF NOT EXISTS ix_source_intel_proposals_run_id "
            "ON source_intel_proposals (run_id)",
            "CREATE INDEX IF NOT EXISTS ix_inbound_webhook_events_tenant_id "
            "ON inbound_webhook_events (tenant_id)",
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
