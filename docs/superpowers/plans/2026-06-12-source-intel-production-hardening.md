# Source Intelligence Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden source-intelligence review operations without waiting for external API access.

**Architecture:** Add database-backed source-intelligence run/proposal tables, a service layer that enforces tenant scope and RBAC, API endpoints for review queue operations, and CLI support for DB-backed local review. Keep external APIs as a research list only.

**Tech Stack:** Python 3.11+, SQLAlchemy, Pydantic v2, Typer, FastAPI, pytest, ruff, mypy.

---

### Task 1: DB-backed review queue

**Files:**
- Modify: `complyos/models/database.py`
- Modify: `complyos/core/repository.py`
- Test: `tests/unit/test_source_intel_service.py`

- [x] **Step 1: Write failing tests**

Tests cover tenant-scoped persistence and review decisions.

- [x] **Step 2: Verify RED**

Focused tests failed on missing `complyos.services.source_intel`.

- [x] **Step 3: Implement DB models and repository methods**

Added `source_intel_runs`, `source_intel_proposals`, save/list/decide methods.

- [x] **Step 4: Verify GREEN**

Focused service tests pass.

### Task 2: Service-layer RBAC and API endpoints

**Files:**
- Modify: `complyos/services/context.py`
- Create: `complyos/services/source_intel.py`
- Modify: `complyos/web/api_v1.py`
- Test: `tests/unit/test_api_v1.py`

- [x] **Step 1: Write failing tests**

Tests cover API listing, decision update, and read-only denial.

- [x] **Step 2: Implement permissions/service/API**

Added source-intel read/run/decide permissions, service validation, and API endpoints.

- [x] **Step 3: Verify GREEN**

Focused API/service tests pass.

### Task 3: CLI DB queue path and external API list

**Files:**
- Modify: `complyos/cli.py`
- Modify: `tests/unit/test_cli_source_intel.py`
- Create: `docs/external-api-research-list.md`
- Modify: `docs/source-intelligence-engine-v0.md`

- [x] **Step 1: Write failing CLI test**

Test covers `source-intel run-fixture --db` and `source-intel review --db`.

- [x] **Step 2: Implement DB-backed CLI path**

Added optional `--db` queue to fixture run/review commands.

- [x] **Step 3: Document external APIs as list-only**

Created the external API research list and kept it separate from implementation.

### Task 4: Scheduler/job execution table and command

**Files:**
- Modify: `complyos/models/database.py`
- Create: `complyos/core/migrations.py`
- Modify: `complyos/core/repository.py`
- Modify: `complyos/services/source_intel.py`
- Modify: `complyos/cli.py`
- Test: `tests/unit/test_source_intel_service.py`
- Test: `tests/unit/test_cli_source_intel.py`
- Test: `tests/unit/test_database.py`

- [x] **Step 1: Write failing tests**

Tests cover schedule creation, due checks, job executions, migration ledger, and CLI scheduled execution.

- [x] **Step 2: Verify RED**

Focused tests failed on missing `create_schedule`, CLI `schedule-add`, missing migration tables, and missing deployment checklist.

- [x] **Step 3: Implement local scheduler/job persistence**

Added `source_intel_schedules`, `source_intel_job_executions`, migration ledger `20260612_source_intel_hardening`, service methods, and CLI commands:

- `complyos source-intel schedule-add --db ... --json`;
- `complyos source-intel schedule-list --db ... --json`;
- `complyos source-intel run-scheduled --db ... --force --json`.

### Task 5: Review UI, export packet, and deployment checks

**Files:**
- Modify: `complyos/web/dashboard.py`
- Modify: `complyos/web/api_v1.py`
- Modify: `complyos/core/release.py`
- Modify: `complyos/cli.py`
- Test: `tests/unit/test_live_dashboard.py`
- Test: `tests/unit/test_api_v1.py`
- Test: `tests/unit/test_release.py`

- [x] **Step 1: Write failing tests**

Tests cover dashboard `/source-intel/review`, API `/api/v1/source-intel/export-packet`, and source-intelligence deployment hardening checks.

- [x] **Step 2: Implement UI/API/export/deployment surfaces**

Added review UI, review-packet export, API export route, `complyos source-intel export-packet`, and `complyos deployment-check --json`.

### Task 6: Documentation and landing-page cohesion

**Files:**
- Modify: `docs/source-intelligence-engine-v0.md`
- Modify: `docs/source-intelligence-api-inventory.md`
- Modify: `docs/external-api-research-list.md`
- Modify: `docs/regwatch-v0.md`
- Modify: `docs/learningops-suite-v0.md`
- Modify: `docs/index.html`

- [x] **Step 1: Keep external APIs list-only**

Documented external APIs as acquisition/research targets only. No paid/keyed API work is required for this hardening slice.

- [x] **Step 2: Update product docs and landing page**

Docs now reflect schedules, job receipts, review UI, export packets, migration ledger, and deployment checks.

## Execution receipts

- RED verification for hardening slice: focused tests failed on missing scheduler, CLI commands, export route, dashboard route, deployment checklist, and migration tables.
- Focused hardening tests: `6 passed`.
- Focused service/API/CLI tests: `9 passed`.
- External APIs documented as research-only in `docs/external-api-research-list.md`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 54 source files`.
- Full pytest: `324 passed, 208 warnings`.
- Smoke: `source-intel schedule-add`, `source-intel run-scheduled --force`, `source-intel export-packet`, and `deployment-check --json` all exited 0.
