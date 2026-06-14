# Multi-tenancy posture

> What ComplyOS guarantees about tenant isolation today, and what must change
> before it can safely serve multiple customers from one shared deployment.
> Companion to the tenant model described in `ARCHITECTURE.md` and the
> follow-up list in `docs/enterprise-hardening-report.md`.

## TL;DR

ComplyOS runs **single-tenant at runtime** with a **tenant-aware data model**.
One deployment serves one organization; every persisted row still carries a
`tenant_id` so the data model is ready for multi-tenancy without a later
migration. **Multi-tenant / SaaS hosting is not built and is a deliberate
stop-and-ask decision** (see the stop rules in
`.omx/plans/complyos-enterprise-remediation.md` §18). In the single-tenant
posture the limitations below are **not exploitable** — there is only one tenant.

## What "tenant-aware data model" means in the code

- Every PII-bearing table (`users`, `learning_records`, `enrollments`, evidence,
  import batches/rows, AI proposals, role bindings, legal holds, retention
  policy, …) has an indexed `tenant_id` column, defaulting to `local-default`.
- Application services accept an `ActorContext` and scope tenant-owned reads and
  writes by `context.tenant_id`. Mutations that load an object by id verify
  `object.tenant_id == context.tenant_id` before acting (e.g. `ImportService.promote`
  and `ImportService.decide`, `PrivacyProgramService` request/hold access,
  `AIProposalService.approve`/`reject`).
- Repository aggregate reads (`list_evidence_ledger`, `list_role_bindings`,
  `list_active_legal_holds`, source-intel proposals, tenant metadata, …) take a
  `tenant_id` and filter on it at the query level.
- Cross-tenant isolation is exercised by tests: `tests/unit/test_tenant_isolation.py`
  (repository layer) and `tests/security/test_api_bola_idor.py` (API surface).

## The single-tenant security boundary (today)

- The runtime assumes **one tenant per deployment**. The CLI and the web shell
  build their `ActorContext` as the local/default tenant.
- The API authenticates the operator with a single shared `COMPLYOS_API_TOKEN`
  (constant-time compare, fail-closed when unset). Within an authenticated
  request, `tenant_id`/`role` are read from `X-Tenant-Id`/`X-Actor-Role` headers.
  In a single-tenant deployment the token holder **is** the tenant, so the header
  simply selects the one tenant — there is no other tenant to reach.

This is safe for customer-hosted / local-first single-tenant use (the frozen
default). It is **not** safe to expose one shared-token deployment to multiple
distinct customers without the changes below.

## What must change before multi-tenant / SaaS

These are tracked as non-blocking follow-ups in
`docs/enterprise-hardening-report.md` and must be closed **before** any
shared-deployment multi-tenant hosting:

1. **Token → tenant binding.** Stop trusting `X-Tenant-Id`/`X-Actor-Role` as free
   headers under a shared token. Bind the tenant (and allowed roles) to the
   credential itself — e.g. per-tenant API tokens or signed claims — so a token
   holder cannot select another tenant. (The current code comment in
   `complyos/web/api_v1.py` already names this threat.)
2. **Repository-layer tenant scoping (defense in depth).** Today several point
   lookups (`get_import_batch`, `list_import_rows`, `get_privacy_request`,
   `get_legal_hold`) are keyed by id only, with the tenant check enforced one
   layer up in the service. Add an optional `tenant_id` filter at the repository
   layer so a future caller cannot bypass the boundary by skipping the service
   check.
3. **MCP tenant selection.** `complyos/api/mcp_server.py` hardcodes
   `tenant_id="local-default"`. Add a `COMPLYOS_MCP_TENANT_ID` (or per-connection
   tenant) before exposing MCP to more than one tenant.
4. **Re-run the BOLA/IDOR suite across all surfaces** (API, CLI, MCP, web) under
   the new credential model, asserting tenant A can never read or mutate tenant
   B's objects on any path.

## Why it is deferred (not a bug)

The plan's frozen defaults (§3) choose **single-tenant runtime + customer-hosted /
local-first** as the first posture, and §18 makes "choose SaaS multi-tenant
hosting as the first implementation target" a stop-and-ask boundary. The
tenant-aware schema means adopting multi-tenancy later is additive, not a rewrite —
but the credential/isolation hardening above is a prerequisite, intentionally
left until the SaaS decision is actually made.
