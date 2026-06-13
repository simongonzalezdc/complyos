# ComplyOS Enterprise Hardening — Remediation Report

> Branch: `simon/enterprise-hardening` · Baseline: `main` (342 tests green)
> Result: 377 tests green (+35 regression tests), ruff + mypy clean. All 3
> CRITICAL and all HIGH/MEDIUM findings remediated; the repository God-object
> split is complete and the security-critical typed-model migration is done. One
> mechanical follow-up remains (see "Remaining work").

## How this was produced

A read-only, multi-lens audit (architecture, domain-modeling, reliability,
security, data-layer, test-quality, surface-parity, slop) surfaced 48 candidate
findings; each was independently re-verified against the actual code, leaving
**46 confirmed** (2 rejected as false positives, including one that wrongly
imported a personal style guide as a product requirement). Findings were then
remediated in dependency order — correctness/security first (locked with
regression tests), behavior-preserving refactors last — each as one atomic,
test-gated commit.

## Findings closed (shipped)

| Sev | Finding | Fix | Commit |
|----|---------|-----|--------|
| 🔴 CRITICAL | Cross-tenant PII export/erasure (no tenant filter; `local-default` fallback) | Real indexed `tenant_id` column on users/learning_records/enrollments; every DSR query tenant-scoped; fallback removed | WP9 |
| 🔴 CRITICAL | Legal-hold spoliation — subject/`system` holds ignored by 4/5 retention queries | Centralized `resolve_active_holds`; subject+tenant+system honored; unlinked datasets fail closed | WP1 |
| 🔴 CRITICAL | Retention purge non-atomic; PII/evidence destroyed with no audit trail on partial failure | Single-transaction `purge_retention_eligible` (deletes + audit log commit/rollback together) | WP1 |
| 🟠 HIGH | API fail-open: unset token ⇒ owner-of-any-tenant via headers | Fail closed unless token set or `COMPLYOS_ALLOW_INSECURE_LOCAL`; constant-time token compare | WP3a |
| 🟠 HIGH | Audit/remediation bypass authorization on CLI + MCP | `require_permission` gates at the surface (PERM_AUDIT_RUN / REMEDIATION_EXECUTE) | WP3b |
| 🟠 HIGH | MCP self-elevates to `privacy_admin`/`owner` (any agent can delete/approve) | All MCP tools route through `_mcp_context`, default least-privileged `agent_service_account`; privileged ops require `COMPLYOS_MCP_ROLE` opt-in | WP3b |
| 🟠 HIGH | Notification retry backoff never enforced (hot-loop); 500-row scan loses deliveries | `due_at` predicate enforces backoff; point-lookup `get_notification_delivery` | WP2 |
| 🟠 HIGH | Source-intel monitor crashes on non-JSON regulator response; one bad source aborts run | Transport guards `response.json()`; monitor degrades per-source to a coverage gap | WP4 |
| 🟠 HIGH | Repository God-object / no indexes / inert FKs (partial: data-layer) | 19 hot-path indexes; removed misleading FK+cascade declarations | WP0 |
| 🟡 MED | Webhook replay (no timestamp freshness); inbound fail-open when secret unset | ±300s freshness window; fail closed without a secret (explicit unsigned opt-in) | WP3a |
| 🟡 MED | Outbound HMAC tested only by prefix; 3 divergent `_signature` copies | One canonical `notification/signing.py`; tamper/round-trip tests | WP2 |
| 🟡 MED | Service layer imports connector private helpers (layer inversion) + duplicated date parsing | Public `connectors/normalization.py`; services import it, not connector privates | WP5 |
| 🟡 MED | Import preview duplicates file-global issues onto every row | File-scoped issues reported once; rows store only own issues; surfaces `PARTIAL_LOAD` on empty files | WP5 |
| 🟡 MED | `_get_notifier` duplicated across CLI + MCP | Shared `build_notifier_from_env()` | WP5 |
| 🟡 MED | Docs claim unqualified API/MCP/CLI parity | Scoped the claim to what the API actually exposes | docs |

New regression tests live in: `test_retention_legal_hold_hardening.py`,
`test_tenant_isolation.py`, `test_inbound_hooks.py`, `test_mcp_authz.py`,
`test_source_intel_resilience.py`, plus additions to outbox/import/db tests.

## New operational env vars

- `COMPLYOS_ALLOW_INSECURE_LOCAL=1` — opt into header-driven role/tenant on the
  API when no `COMPLYOS_API_TOKEN` is set (local-only). Without it, the API
  fails closed.
- `COMPLYOS_MCP_ROLE` — raise the MCP agent role above the proposal-only default
  (`agent_service_account`) when a service account genuinely needs more (e.g.
  `privacy_admin`, `compliance_manager`, `owner`).

## Also shipped (second pass)

| Item | What shipped | Commit |
|----|---------|--------|
| H9 — erasure completeness | `delete_subject_records` now also erases the subject's raw identifiers from `import_rows` (tenant-scoped, same transaction). Decision: notification events + count-only audit logs are retained as process-audit evidence governed by retention. | WP6a |
| Typed API errors | `_bad_request` maps PermissionError/AuthorizationError to 403 (not 400). | WP6a |
| H6 — API parity | Added `GET /audit`, `/report`, `/users/{id}/status`, `/digest`, `/connectors/health`, `POST /remediate`, each `require_permission`-gated; shared shaping in `core/audit_views.py` keeps MCP and API identical. File-writing exports stay CLI/MCP-only. | WP6b |
| H8 — workflow enums | Added `ImportBatchStatus`/`ImportRowStatus`/`PrivacyRequestType`/`LegalHoldScope` StrEnums; removed the decorative `IMPORT_BATCH_STATES`; request-type/scope validation is now enum-typed. | WP7 |
| H8 — PrivacyRequest model | The DSR/privacy request (the authorization surface for export/erasure) is now a Pydantic `PrivacyRequest` carried end to end; the controller-approval gate is the typed `is_controller_approved()`, replacing scattered isinstance/dict chains. | WP7 |
| **H7 — repository split (complete)** | The 2000-line `LocalRepository` God-object is decomposed into 7 cohesive files (core-audit 453 · privacy 551 · notification 306 · source-intel 267 · import 226 · mappers 374 · base 63) composed via mixins behind a typed `RepositoryBase`. **Zero public-API change.** | WP8 |

## Remaining work (one mechanical follow-up)

**Type the remaining data-record envelopes.** LegalHold, RetentionPolicy, import
batches/rows/decisions, and AI proposals still cross the repository boundary as
`dict[str, Any]`. The security-critical envelope (PrivacyRequest + the approval
gate) is now typed; these remaining ones are data DTOs (no authorization
decision rides on them), so converting them to Pydantic models is uniform,
lower-risk mechanical work — best done as a focused pass, de-risked by the
regression net added here. (A repository Protocol + composition root to drop the
`or LocalRepository()` default-construction is an optional further refinement;
the split itself is complete.)

## Verify

```bash
.venv/bin/ruff check complyos tests
.venv/bin/mypy complyos
.venv/bin/python -m pytest -q
```
