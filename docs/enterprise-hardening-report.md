# ComplyOS Enterprise Hardening — Remediation Report

> Branch: `simon/enterprise-hardening` · Baseline: `main` (342 tests green)
> Result: 372 tests green (+30 regression tests), ruff + mypy clean, +1,599/−492 across 31 files.

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

## Remaining work (planned follow-ups)

These are larger, behavior-preserving refactors or items that need a product/
legal decision. They are best landed as their own focused, reviewed PRs.

1. **WP7 — Typed domain models (HIGH, large).** Replace `dict[str, Any]` for
   PrivacyRequest, LegalHold, RetentionPolicy, import batches/rows/decisions,
   AI proposals, and the evidence-ledger write path with Pydantic models +
   StrEnums; move the controller-approval gate onto the model. Removes the
   primitive-obsession surface mypy can't see at the PII boundary.
2. **WP8 — Repository split + composition root (HIGH, large).** Split the
   ~1,900-line `LocalRepository` into aggregate repositories (Audit, Import,
   Privacy, SourceIntel, Notification) behind a shared sessionmaker; add a
   composition root and a narrow repository Protocol; drop `or LocalRepository()`
   default-construction (61 inline call sites).
3. **WP6 — API parity endpoints (HIGH).** Add audit/report/status/digest/
   remediation/health/rule endpoints to the FastAPI surface routed through the
   context-gated services. (Docs were corrected in the interim.)
4. **WP6 — Erasure completeness, H9 (HIGH, needs decision).** Subject deletion
   currently leaves the subject's `user_id` in `import_rows` and `subject_id` in
   `notification_events`. The correct fix enumerates every subject-linked table
   and reports `PARTIAL` vs `COMPLETED` — but *which* records erasure should
   remove vs retain (audit/notification history) is a compliance/counsel call.
5. **WP6 — Typed API errors (MED).** Introduce typed domain errors so a
   `PermissionError` returns 403 (not 400) and internal identifiers are not
   echoed verbatim to clients.

## Verify

```bash
.venv/bin/ruff check complyos tests
.venv/bin/mypy complyos
.venv/bin/python -m pytest -q
```
