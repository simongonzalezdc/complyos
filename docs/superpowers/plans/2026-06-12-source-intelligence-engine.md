# Source Intelligence Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one shared source-intelligence pipeline that powers both RegWatch regulatory change proposals and AI-assisted microlearning suggestions.

**Architecture:** Add a small `complyos.source_intel` package with source definitions, crawl snapshots, signals, proposals, and an engine that fans each snapshot out to adapters. Add `complyos.regwatch` and `complyos.microlearning` adapters as thin policy/scoring layers over the shared engine. Keep the first slice deterministic, auditable, and human-approval-first.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, ruff, mypy. No live network dependency in v0 tests.

---

### Task 1: Shared source-intelligence models and engine

**Files:**
- Create: `complyos/source_intel/__init__.py`
- Create: `complyos/source_intel/models.py`
- Create: `complyos/source_intel/engine.py`
- Test: `tests/unit/test_source_intelligence.py`

- [x] **Step 1: Write failing tests**

Create tests proving:
- one source snapshot can feed multiple adapters
- every proposal preserves source hash, source URL, evidence chain, and `needs_review`
- source freshness/change detection is content-hash based

- [x] **Step 2: Run the tests and confirm RED**

Run: `uv run --extra dev pytest tests/unit/test_source_intelligence.py -q`

Expected: import failure for `complyos.source_intel`.

- [x] **Step 3: Implement models and engine**

Implement:
- `SourceDefinition`
- `SourceSnapshot`
- `SourceSignal`
- `SourceProposal`
- `SourceIntelAdapter`
- `SourceIntelEngine`
- `build_snapshot()`

- [x] **Step 4: Run focused tests**

Run: `uv run --extra dev pytest tests/unit/test_source_intelligence.py -q`

Expected: all source-intelligence tests pass.

### Task 2: RegWatch adapter

**Files:**
- Create: `complyos/regwatch/__init__.py`
- Create: `complyos/regwatch/adapter.py`
- Test: `tests/unit/test_source_intelligence.py`

- [x] **Step 1: Write failing tests**

Add tests proving an official regulatory source containing obligation language creates a RegWatch proposal with:
- `signal_type="regulatory_change"`
- jurisdiction preserved
- high confidence score
- human approval gate
- suggested compliance action

- [x] **Step 2: Implement deterministic RegWatch adapter**

Implement keyword-based v0 scoring for official/legal/regulator sources. Treat unofficial sources conservatively.

- [x] **Step 3: Run focused tests**

Run: `uv run --extra dev pytest tests/unit/test_source_intelligence.py -q`

Expected: all tests pass.

### Task 3: Microlearning adapter

**Files:**
- Create: `complyos/microlearning/__init__.py`
- Create: `complyos/microlearning/adapter.py`
- Test: `tests/unit/test_source_intelligence.py`

- [x] **Step 1: Write failing tests**

Add tests proving a credible training/source item creates a microlearning proposal with:
- `signal_type="microlearning_opportunity"`
- module outline
- learning objectives
- check-for-understanding question
- source citation and human approval gate

- [x] **Step 2: Implement deterministic Microlearning adapter**

Implement keyword/topic-based v0 scoring. Keep outputs as proposals, never auto-publish modules.

- [x] **Step 3: Run focused tests**

Run: `uv run --extra dev pytest tests/unit/test_source_intelligence.py -q`

Expected: all tests pass.

### Task 4: Documentation and verification

**Files:**
- Create: `docs/source-intelligence-engine-v0.md`
- Modify: `docs/regwatch-v0.md`
- Modify: `docs/learningops-suite-v0.md`

- [x] **Step 1: Document the shared-under-the-hood design**

Document that RegWatch and Microlearning Radar use the same source registry, crawl snapshot, scoring, proposal, and approval primitives.

- [x] **Step 2: Run full verification**

Run:
- `uv run --extra dev ruff check .`
- `uv run --extra dev mypy complyos`
- `uv run --extra dev pytest -q`

Expected:
- ruff passes
- mypy passes
- pytest passes

### Self-review

- Spec coverage: plan covers the shared engine, RegWatch adapter, Microlearning adapter, docs, and verification.
- Placeholder scan: no implementation placeholders are left for the v0 slice.
- Type consistency: all tasks use the same SourceDefinition/Snapshot/Signal/Proposal vocabulary.


## Execution receipts

- RED verified before implementation: `uv run --extra dev pytest tests/unit/test_source_intelligence.py -q` failed on missing source-intelligence/microlearning import.
- Focused source-intelligence tests: `4 passed`.
- Ruff: `All checks passed!`.
- Mypy: `Success: no issues found in 49 source files`.
- Full pytest: `305 passed, 163 warnings`.
