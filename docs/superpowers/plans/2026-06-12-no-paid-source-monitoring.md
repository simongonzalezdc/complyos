# No-Paid Source Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build as much of RegWatch/MicroLearn source monitoring as possible without paid APIs: free/public endpoint client contracts, a local proposal review queue, CLI commands, and an API research inventory.

**Architecture:** Keep live network access optional and injectable. Public source clients convert fetched official data into `SourceSnapshot` objects; `SourceMonitor` feeds those snapshots into the existing `SourceIntelEngine`; `SourceReviewStore` persists proposals as local JSONL so reviewers can list and decide without a SaaS database. CLI commands expose source listing, fixture-backed runs, and review decisions.

**Tech Stack:** Python 3.11+, Pydantic v2, httpx, Typer, pytest, ruff, mypy. Tests use fake transports and local temp files; no paid accounts or live network dependency.

---

### Task 1: Public/free source clients

**Files:**
- Create: `complyos/source_intel/clients.py`
- Modify: `complyos/source_intel/__init__.py`
- Test: `tests/unit/test_source_clients.py`

- [x] **Step 1: Write failing tests**

Create tests proving Federal Register and eCFR client adapters convert fake HTTP responses into source snapshots and coverage gaps without making real network calls.

- [x] **Step 2: Verify RED**

Run: `uv run --extra dev pytest tests/unit/test_source_clients.py -q`
Expected: import failure for `complyos.source_intel.clients`.

- [x] **Step 3: Implement clients**

Implement `HTTPResponse`, `HTTPTransport`, `HttpxTransport`, `FederalRegisterClient`, `ECFRClient`, `SourceFetchReport`, and `free_public_source_definitions()`.

- [x] **Step 4: Verify GREEN**

Run: `uv run --extra dev pytest tests/unit/test_source_clients.py -q`
Expected: all tests pass.

### Task 2: Local monitor and review queue

**Files:**
- Create: `complyos/source_intel/monitor.py`
- Create: `complyos/source_intel/store.py`
- Modify: `complyos/source_intel/__init__.py`
- Test: `tests/unit/test_source_monitor_store.py`

- [x] **Step 1: Write failing tests**

Create tests proving the monitor fans fetched snapshots to RegWatch/MicroLearn and the JSONL store lists/decides proposals while preserving source hash and approval state.

- [x] **Step 2: Verify RED**

Run: `uv run --extra dev pytest tests/unit/test_source_monitor_store.py -q`
Expected: import failure for monitor/store.

- [x] **Step 3: Implement monitor/store**

Implement deterministic `SourceMonitor.run()` and `SourceReviewStore.save_many/list/decide`.

- [x] **Step 4: Verify GREEN**

Run: `uv run --extra dev pytest tests/unit/test_source_monitor_store.py -q`
Expected: all tests pass.

### Task 3: CLI and docs

**Files:**
- Modify: `complyos/cli.py`
- Create: `tests/unit/test_cli_source_intel.py`
- Modify: `docs/source-intelligence-engine-v0.md`
- Create: `docs/source-intelligence-api-inventory.md`

- [x] **Step 1: Write failing CLI tests**

Create tests proving `source-intel sources`, `source-intel run-fixture`, and `source-intel review` work without network or paid APIs.

- [x] **Step 2: Verify RED**

Run: `uv run --extra dev pytest tests/unit/test_cli_source_intel.py -q`
Expected: command does not exist.

- [x] **Step 3: Implement CLI/docs**

Add a Typer subapp for source intelligence and document free vs key-required APIs.

- [x] **Step 4: Verify full stack**

Run:
- `uv run --extra dev ruff check .`
- `uv run --extra dev mypy complyos`
- `uv run --extra dev pytest -q`

Expected: all checks pass.

### Self-review

- Spec coverage: free/public endpoint contracts, no-paid local queue, CLI, and API inventory are covered.
- Placeholder scan: no `TODO` or fake paid dependency is introduced.
- Type consistency: clients return `SourceFetchReport`, monitor returns `SourceMonitorRun`, store persists `SourceProposal` JSON.


## Execution receipts

- RED verified: new source client/monitor/store tests failed on missing modules.
- RED verified: CLI tests failed on missing `source-intel` commands.
- Focused source-intel tests: `10 passed`.
- Added no-paid surfaces: Federal Register client, eCFR client, fixture run, public dry-run/live command, approved text upload command, local JSONL review queue.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 52 source files`.
- Full pytest: `310 passed, 163 warnings`.
- CLI smoke: fixture run created 2 proposals and review queue listed 2 proposals.
