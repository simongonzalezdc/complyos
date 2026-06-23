# Suite-module pattern

The repeatable shape every LearningOps Suite module should follow, so the next
~15 modules look and behave like one product instead of fifteen one-offs. The
**Intake** module (`complyos/services/intake.py`) is the tracer-bullet that
established this pattern; read it alongside this doc.

This pattern is a specialization of the existing ComplyOS conventions in
`AGENTS.md` (services own authz, tenant scoping is real, Pydantic v2, claim
boundary). It does not replace them — it tells you *where the seams go* for a
"request → proposal → human-approval" suite module.

## The five beats

A suite module is a tenant-scoped service with these five beats. Intake is the
worked example in parentheses.

1. **Capture** — a `require_permission`-gated write of a typed domain model in a
   non-committal state. Capturing intent is never the same as agreeing to do the
   work, so the initial status is a draft. *(`create_request(...)` → a typed
   `TrainingRequest`, status `DRAFT`.)*

2. **Draft packet (proposal-only)** — a deterministic, PII-light draft that
   restates the captured request, flags what is **missing**, and *suggests* next
   steps (priority, routing, etc.). The packet is a typed model that carries
   `confirms_scope = False` and `requires_human_confirmation = True`, and the
   drafting call writes **no** state change. Adversarial/free-text input is inert
   here: it can only become a *suggestion*, never a control-path decision.
   *(`draft_packet(...)` → a typed `IntakePacket`; deterministic missing-info +
   priority + routing.)*

3. **Human-approval / confirm gate** — a single, separately-permissioned step
   that is the **only** path from the draft state to the committed state. It
   stamps who approved and when, so the approval is attributable. This is the
   module's guardrail from the suite spec. *(`confirm_scope(...)` →
   `DRAFT → CONFIRMED`, stamping `confirmed_by` / `confirmed_at`.)*

4. **Action log** — every capture, draft, and confirm writes an
   `save_action_log(...)` entry (`object_type` = the module's entity), so the
   evidence trail explains what happened and who did it.

5. **Surfaces + tests + maturity flip** — the same service is reachable on CLI,
   API v1, and MCP with cross-surface parity, and the module's maturity label in
   `docs/learningops-suite-v0.md` flips from **Synthetic demo** to **Live** only
   *after* it is implemented and tested.

## The authorization split (load-bearing)

Mirror the attestation/AI-proposal split. Two permissions per module:

- **`<module>:submit`** — gates capture + draft + read (the proposal-only side).
  The least-privilege `agent_service_account` role **holds** this, so an AI/agent
  can triage and propose. *(`intake:submit`.)*
- **`<module>:confirm`** (or `:approve`) — gates only the human-approval step.
  The `agent_service_account` role **deliberately lacks** this, so an AI/agent
  can never confirm scope / approve work. *(`intake:confirm`.)*

Wire both into `complyos/services/context.py`:

- add the `PERM_*` constants and include them in `ALL_PERMISSIONS`;
- grant both to human-operated roles (e.g. `compliance_manager`);
- grant **only** `:submit` to `agent_service_account`, with a comment saying why
  `:confirm` is withheld.

On MCP, the privileged confirm tool must fail closed for the default role (it is
covered by the mutating-tool denial test in `tests/unit/test_cli_mcp_parity.py`).

## Tenant scoping + claim boundary

- **Tenant scoping is real.** Persist `tenant_id` on the row; every list query
  filters on it; cross-tenant access to a single record raises `PermissionError`
  (ownership, not permission) via a `_require_<entity>` helper that compares
  `record.tenant_id` to `context.tenant_id`.
- **Claim boundary.** A module records *scope intent, readiness, evidence, or
  human approval*. It never asserts anyone is "certified" or "compliant". Keep
  the module's docstrings and outputs in that lane; a test should assert the
  outputs contain no certification/compliance claim.

## Deterministic by default, model optional

Drafting must have a deterministic baseline that needs no model. You **may** reuse
the provider seam in `complyos/services/ai_providers.py` for richer
missing-info/routing text, but only with a deterministic fallback (a model
outage must never block a draft). Intake's v0 is fully deterministic; the
provider seam is a documented future hook, not a dependency.

## Persistence

Follow the aggregate-mixin shape used by source-intel / notifications:

1. add a `DB<Entity>` ORM model in `complyos/models/database.py` (with
   `tenant_id` defaulting to `local-default`);
2. add an idempotent `CREATE TABLE IF NOT EXISTS` migration in
   `complyos/core/migrations.py` (+ a `(tenant_id, status)` index);
3. add a `_to_<entity>` mapper in `complyos/core/repository_mappers.py`;
4. add a `<module>_repo.py` mixin (save / get / list / status-transition, all
   tenant-scoped) and compose it into `LocalRepository`.

## Surfaces (cross-surface parity)

Expose the same service three ways, mirroring the attestation wiring:

- **CLI** (`complyos/cli.py`): a Typer sub-app `<module>` with `submit` / `list`
  / `confirm` commands, registered via `app.add_typer(...)`.
- **API v1** (`complyos/web/api_v1.py`): `POST /api/v1/<module>`,
  `GET /api/v1/<module>`, `POST /api/v1/<module>/{id}/confirm`, with
  `AuthorizationError → 403` and `ValueError → 400` mapping.
- **MCP** (`complyos/api/mcp_server.py`): `submit_<module>` + `list_<module>`
  (agent-allowed) and `confirm_<module>_scope` (privileged), each building the
  context via `_mcp_context(...)`.

Add the module's rows to `PARITY_MATRIX` and the confirm tool to
`MUTATING_MCP_TOOLS` in `tests/unit/test_cli_mcp_parity.py`.

## Docs to update when you add a module

- flip the module's maturity label to **Live** in `docs/learningops-suite-v0.md`;
- if you add a service and/or permissions, update the explicit counts the
  doc-count guard checks (`tests/unit/test_docs_match_code.py`): the
  `N-permission catalog` claims and the `N services` claims must match the code.

## Checklist

- [ ] Typed domain models (request + packet), Pydantic v2, claim-boundary docstrings.
- [ ] `PERM_<MODULE>_SUBMIT` + `PERM_<MODULE>_CONFIRM` wired into roles
      (agent gets submit only).
- [ ] `DB<Entity>` model + migration + mapper + repo mixin composed into `LocalRepository`.
- [ ] Service: capture (`require_permission`) → draft (proposal-only, no state
      change) → confirm (elevated permission) → list (tenant-scoped); action log
      on every write; cross-tenant guard.
- [ ] CLI / API v1 / MCP surfaces with cross-surface parity.
- [ ] Tests: lifecycle, missing-info, agent-denied-confirm, tenant scoping,
      claim boundary, cross-surface parity.
- [ ] Maturity label flipped to **Live**; doc-count guard green.
- [ ] `uv run --extra dev ruff check ...` / `mypy` / `pytest -q` all pass.
