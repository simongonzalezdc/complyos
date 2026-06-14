# Migration & Rollback Guide

> Operational runbook for the tenant-aware schema and the additive migrations
> introduced during enterprise hardening. Implements the rollback rules in
> `.omx/plans/complyos-enterprise-remediation.md` §5.3.

ComplyOS is local-first and single-tenant by default, with a **tenant-aware data
model** (every PII-bearing table carries an indexed `tenant_id` defaulting to
`local-default`). Migrations are **additive** during a hardening cycle: new
tables and nullable/defaulted columns are added, but existing columns are not
dropped. This keeps every step reversible.

## Before any migration

1. **Back up first.** SQLite is a single file — copy it while the app is stopped:
   ```bash
   cp complyos.db "complyos.db.bak-$(date +%Y%m%dT%H%M%S)"
   ```
   For an evidence-grade snapshot, also export the audit/evidence report
   (`complyos export`) so the pre-migration state is independently recorded.
2. **Record the schema version / commit** you are migrating from.
3. **Verify gates are green** on the target build before promoting it:
   ```bash
   .venv/bin/ruff check complyos tests && .venv/bin/mypy complyos && .venv/bin/python -m pytest -q
   ```

## Migration order (additive)

The tenant-aware migration was applied in this dependency order (see plan §5.2):

1. Add the `Tenant` table; create the default `local-default` tenant.
2. Add nullable/defaulted `tenant_id` to existing persisted tables.
3. Backfill existing rows to `local-default`.
4. Add indexes on `(tenant_id, id)` and source-system / source-record keys.
5. Add actor / role-binding / action-log tables.
6. Add import / approval / AI-provenance tables.
7. Enable service-layer permission checks in read-only mode.
8. Require `ActorContext` on service calls.
9. Enforce non-null tenant IDs **only after** backfill tests pass.

## Rollback rules (§5.3)

- **Additive until proven.** A migration stays additive until the service-layer
  tests pass against the migrated database. Do not drop legacy columns during a
  hardening cycle.
- **Abort before enforcing non-null `tenant_id`.** If the backfill (step 3) does
  not cover every row, STOP before step 9. Enforcing the non-null constraint on
  an incompletely-backfilled table is the one irreversible step — never run it
  until a backfill-count check confirms zero unscoped rows.
- **Import promotion is transactional.** If promotion fails mid-transaction, no
  active learning records change; the batch remains `QUARANTINED` (or
  `PROMOTION_FAILED`) with an evidence/action-log entry. There is nothing to roll
  back — the failure is already atomic (see `ImportService.promote` and the
  `test_import_adversarial` / `test_connector_failure` suites).
- **Retention purge is transactional.** `purge_retention_eligible` deletes and
  writes its audit log in a single transaction; a partial failure rolls back the
  whole purge, so PII/evidence is never destroyed without an audit trail.

## To roll back

Because migrations are additive, rollback is "stop using the new build," not "un-migrate":

1. Stop the service.
2. Restore the pre-migration backup:
   ```bash
   cp "complyos.db.bak-<timestamp>" complyos.db
   ```
3. Redeploy the previous build (the commit recorded in step 2 of *Before*).
4. The additive tables/columns left behind by a forward migration are inert to
   an older build (it ignores columns it does not read), so restoring the backup
   is sufficient; no destructive down-migration is required.

## PostgreSQL note

The data layer targets SQLite for local-first deployments and is written to be
PostgreSQL-URL compatible. When running against PostgreSQL, use the database's
native backup (`pg_dump`) in place of the file copy, and run the same additive
order inside a transaction per step. The rollback rules above are unchanged.
