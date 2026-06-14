# AGENTS.md — working in the ComplyOS repo

Entry point for AI agents (and humans) doing engineering work here. Read this
before changing code, then `CONTEXT.md` (domain language) and `ARCHITECTURE.md`
(layering) for anything non-trivial.

## The quality gate (run before every commit)

One command runs lint → type-check → tests and then prompts to commit:

```bash
./scripts/ship.sh ["commit message"]
```

Or run the gate steps directly (these are exactly what Forgejo CI enforces on
push/PR — keep them in lock-step):

```bash
uv run --extra dev ruff check complyos tests
uv run --extra dev mypy complyos
uv run --extra dev pytest -q
```

A change is not done until all three pass. CI (`.forgejo/workflows/ci.yml`) runs
the same three; do not let the local gate drift more lenient than CI.

## Conventions that are load-bearing here (compliance product)

- **Services own authorization.** Every tenant-data operation enters a service
  with an `ActorContext` and calls `require_permission(...)`. Don't bypass a
  service from the CLI/MCP/API surfaces — gate at the surface or go through the
  service. The core auditor/remediation engines are gated at the surface.
- **Tenant scoping is real.** `users`, `learning_records`, `enrollments`, and the
  evidence/privacy tables carry a `tenant_id` column; every PII query filters on
  it. Never reintroduce a `local-default` fallback in export/erasure paths.
- **Domain models are Pydantic v2.** Prefer typed models over `dict[str, Any]`
  at boundaries, especially on PII/evidence paths.
- **Shared LMS normalization** lives in `complyos/connectors/normalization.py`
  (public) — import it; don't reach into a connector's private helpers.
- **Commits are atomic and descriptive** (one logical change each), end with the
  `Co-Authored-By` trailer, and only land on a feature branch + PR.
- **Compliance language stays scoped** (readiness/control-mapping, not
  "SOC 2/GDPR/FERPA certified"); AI is proposal-only.

## Operational env vars that change behavior

| Var | Effect |
|-----|--------|
| `COMPLYOS_API_TOKEN` | Bearer token for the API. **Unset = fail closed** unless `COMPLYOS_ALLOW_INSECURE_LOCAL` is set. |
| `COMPLYOS_ALLOW_INSECURE_LOCAL=1` | Opt into header-driven role/tenant on the API with no token (local-only). |
| `COMPLYOS_MCP_ROLE` | Raise the MCP agent above the proposal-only default (`agent_service_account`), e.g. `privacy_admin`. |
| `COMPLYOS_INBOUND_WEBHOOK_SECRET` | HMAC secret for inbound hooks; absent = fail closed (unsigned rejected). |

## Map

- `CONTEXT.md` — domain glossary (Learner/User, Learning Item/Course, etc.).
- `ARCHITECTURE.md` — layering (connectors → core → services → CLI/MCP/API).
- `docs/enterprise-hardening-report.md` — recent security/correctness fixes and
  the remaining planned refactors.
