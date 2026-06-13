# Notification Outbox and Hook Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a DB-backed notification outbox and outbound hook event pipeline so scheduled jobs can enqueue auditable notifications without making the job itself depend on Slack, Teams, SMTP, or customer webhook uptime.

**Architecture:** Persist immutable notification events and per-channel delivery rows, then drain pending deliveries through a CLI worker. Source-intelligence scheduled runs enqueue local outbox events by default; delivery remains separate, retryable, auditable, and dry-run capable.

**Tech Stack:** Python 3.11+, SQLAlchemy, Typer, httpx, pytest, respx, ruff, mypy.

---

### Task 1: DB-backed notification outbox

**Files:**
- Modify: `complyos/models/database.py`
- Modify: `complyos/core/migrations.py`
- Modify: `complyos/core/repository.py`
- Create: `complyos/services/notifications.py`
- Test: `tests/unit/test_notification_outbox_service.py`

- [x] **Step 1: Write failing service tests**

Test that `NotificationOutboxService.enqueue_event()` persists one event and one delivery per requested channel, includes a payload hash, stays tenant-scoped, and writes an action log.

- [x] **Step 2: Verify RED**

Run `uv run --extra dev pytest -q tests/unit/test_notification_outbox_service.py`; expected failure is missing `complyos.services.notifications`.

- [x] **Step 3: Implement models, migration, repository, and service**

Add `notification_events`, `notification_deliveries`, and migration `20260613_notification_outbox_hooks`. Add repository methods for save/list/mark. Add service methods: `enqueue_event`, `list_pending_deliveries`, `mark_delivery_sent`, `mark_delivery_failed`, and `mark_delivery_skipped`.

- [x] **Step 4: Verify GREEN**

Run the focused test and confirm it passes.

### Task 2: Hook sender and CLI drain

**Files:**
- Create: `complyos/notification/outbox.py`
- Modify: `complyos/cli.py`
- Test: `tests/unit/notification/test_outbox.py`
- Test: `tests/unit/test_cli_notifications.py`

- [x] **Step 1: Write failing tests**

Test signed webhook headers, missing-channel skip behavior, CLI dry-run, and CLI send path with mocked HTTP.

- [x] **Step 2: Verify RED**

Run `uv run --extra dev pytest -q tests/unit/notification/test_outbox.py tests/unit/test_cli_notifications.py`.

- [x] **Step 3: Implement sender and CLI**

Add `WebhookEventSender` with HMAC signature headers and `notifications list` / `notifications drain --dry-run/--send` Typer commands. Resolve channel URLs from env without logging secrets.

- [x] **Step 4: Verify GREEN**

Run the focused tests and confirm they pass.

### Task 3: Source-intelligence scheduled-run enqueue

**Files:**
- Modify: `complyos/cli.py`
- Modify: `tests/unit/test_cli_source_intel.py`
- Modify: `docs/source-intelligence-engine-v0.md`
- Modify: `docs/source-intelligence-api-inventory.md`

- [x] **Step 1: Write failing CLI integration test**

Test that `source-intel run-scheduled --db ... --force --json` creates notification events and deliveries while still recording the source-intelligence job execution.

- [x] **Step 2: Verify RED**

Run `uv run --extra dev pytest -q tests/unit/test_cli_source_intel.py::test_source_intel_run_scheduled_enqueues_notification_events`.

- [x] **Step 3: Wire enqueue after successful local scheduled runs**

After a schedule succeeds, enqueue `source_intel.run.completed`; also enqueue `source_intel.proposals_waiting` when proposals exist and `source_intel.coverage_gap_found` when coverage gaps exist. Do not make network calls in `run-scheduled`.

- [x] **Step 4: Verify GREEN**

Run the focused source-intel CLI tests.

### Task 4: Documentation, deployment checks, and verification

**Files:**
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `docs/source-intelligence-engine-v0.md`
- Modify: `docs/source-intelligence-api-inventory.md`
- Modify: `docs/index.html`
- Modify: `complyos/core/release.py`
- Modify: `tests/unit/test_release.py`

- [x] **Step 1: Update docs and deployment check tests**

Document outbox, dry-run drain, signed hooks, no-secret logging, and no paid APIs.

- [x] **Step 2: Run all verification**

Run:

```bash
uv run --extra dev ruff check .
uv run --extra dev mypy complyos
uv run --extra dev pytest -q
uv run complyos notifications drain --db <tmp-db> --dry-run --json
```

- [ ] **Step 3: Leak audit and commit**

Run staged diff secret/path scan, then commit locally with message `Add notification outbox and hook events`.

## Execution receipts

- RED verification: focused tests failed on missing `complyos.services.notifications` and `complyos.notification.outbox`.
- Focused outbox/hook/source-intel tests: `7 passed`.
- Focused hardening/release/database tests: `9 passed`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 56 source files`.
- Full pytest: `331 passed, 248 warnings`.
- Smoke: `source-intel schedule-add`, `source-intel run-scheduled --force`, `notifications list`, `notifications drain --dry-run`, and `deployment-check --json` all exited 0.
