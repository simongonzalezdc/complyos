# Provider-Neutral Notification Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Close the generic notification/hook infrastructure gaps that do not require paid APIs, live customer credentials, or provider-specific LMS/HRIS customization.

**Architecture:** Keep ComplyOS local-first and provider-neutral: durable tables own preferences, inbound receipts, and outbox deliveries; services emit auditable events; CLI/API surfaces expose the same controls; deploy templates show how to run workers without touching live systems. Email and webhooks stay adapter-based so real destinations are configured later through environment variables.

**Tech Stack:** Python 3.12, SQLAlchemy local SQLite models/migrations, FastAPI API v1, Typer CLI, existing SMTP and HTTPX notification adapters, pytest/ruff/mypy verification.

---

## File Structure

- Modify `complyos/models/database.py`: add `DBNotificationPreference` and `DBInboundWebhookEvent`.
- Modify `complyos/core/migrations.py`: add idempotent migrations for preferences and inbound hook receipts.
- Modify `complyos/core/repository.py`: persist/list preferences and inbound webhook receipts.
- Modify `complyos/services/notifications.py`: enforce channel/event kill switches and expose preference methods.
- Create `complyos/services/inbound_hooks.py`: parse, redact, verify, hash, and persist generic inbound hook receipts.
- Modify `complyos/notification/outbox.py`: add SMTP-backed email delivery for outbox events.
- Modify `complyos/cli.py`: route email deliveries, add preference CLI commands, enqueue audit schedule events.
- Modify `complyos/core/scheduler.py`: carry audit severity data into scheduled results.
- Modify `complyos/web/api_v1.py`: add inbound hook and notification preference endpoints.
- Modify `complyos/services/privacy.py`: emit privacy/retention/hold events into the outbox.
- Add `deploy/systemd/*.service`, `deploy/systemd/*.timer`, `deploy/cron.d/complyos-notifications`, and `deploy/forgejo/notification-worker.yml`: generic worker templates only.
- Modify docs: `README.md`, `ARCHITECTURE.md`, `docs/index.html`, `docs/source-intelligence-engine-v0.md`, and `docs/regwatch-v0.md`.
- Add/modify tests:
  - `tests/unit/test_notification_outbox_service.py`
  - `tests/unit/notification/test_outbox.py`
  - `tests/unit/test_cli_notifications.py`
  - `tests/unit/test_api_v1.py`
  - `tests/unit/test_privacy_service.py`
  - `tests/unit/test_release.py`
  - `tests/unit/test_database.py`

## Task 1: Preferences / Kill Switches

- [x] Add failing tests showing a disabled channel suppresses deliveries while keeping an auditable event.
- [x] Implement `notification_preferences` model, migration, repository methods, and `NotificationOutboxService.set_preference/list_preferences`.
- [x] Make `enqueue_event` filter delivery channels using exact event, wildcard event, exact channel, and wildcard channel preferences.
- [x] Add CLI/API preference management.

## Task 2: Email Outbox Channel

- [x] Add failing tests showing `email` deliveries use SMTP config, recipients from payload/default env, and skip safely when unconfigured.
- [x] Implement `EmailEventSender` in `complyos/notification/outbox.py`.
- [x] Update `complyos notifications drain --send` to route email deliveries through SMTP and webhook-like channels through `WebhookEventSender`.

## Task 3: Generic Inbound Webhooks

- [x] Add failing API tests for `POST /api/v1/hooks/inbound/{source}` with token auth, tenant scope, HMAC validation, and stored redacted receipt.
- [x] Implement `inbound_webhook_events` model, migration, repository methods, and `InboundHookService`.
- [x] Add the API route and fail closed when `COMPLYOS_INBOUND_WEBHOOK_SECRET` is configured and signature verification fails.

## Task 4: Event Wiring

- [x] Add tests proving privacy requests, approvals, legal holds, delete-blocked, delete-completed, retention runs, and scheduled audits enqueue outbox events.
- [x] Wire privacy service event emissions after successful action logs.
- [x] Wire scheduled audit CLI runs to enqueue `audit.completed` and `audit.high_risk_gaps_found` when applicable.

## Task 5: Worker Templates and Release Checks

- [x] Add generic systemd, cron, and Forgejo Action worker templates with placeholder paths and environment files only.
- [x] Extend deployment checklist checks to cover email outbox, inbound hooks, preferences, and worker templates.
- [x] Update docs/landing page with the durable notification and hook architecture.

## Task 6: Verification and Local Commit

- [x] Run focused tests for notification, inbound hooks, privacy, scheduler, release, and database migrations.
- [x] Run `uv run --extra dev ruff check .`.
- [x] Run `uv run --extra dev mypy complyos`.
- [x] Run `uv run --extra dev pytest -q`.
- [x] Run `git diff --check` and a public-safe leak scan before commit.
- [x] Commit locally only; do not push.
