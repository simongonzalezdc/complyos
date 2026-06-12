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

## Execution receipts

- Focused service/API/CLI tests: `9 passed`.
- External APIs documented as research-only in `docs/external-api-research-list.md`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 53 source files`.
- Full pytest: `319 passed, 181 warnings`.
