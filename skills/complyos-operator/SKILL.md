---
name: complyos-operator
description: Operate ComplyOS safely through readiness, imports, evidence, API, MCP, and CLI surfaces.
---

# ComplyOS operator

Use this skill when operating ComplyOS as an agent or assistant.

## Mandatory sequence

1. Check readiness before customer-facing or mutating work:
   ```bash
   complyos readiness --json
   ```
2. For CSV/import work, preview first:
   ```bash
   complyos import preview path/to/file.csv --json
   ```
3. Do not promote if any row is `REJECTED`, `NEEDS_DECISION`, or `PENDING`.
4. Promote only after the preview is clean or the required decisions are recorded:
   ```bash
   complyos import promote <batch-id> --json
   ```
5. Pull evidence and cite hashes in summaries:
   ```bash
   complyos evidence list --tenant local-default --json
   ```
6. For security/auditor review, collect the readiness-only evidence packet:
   ```bash
   complyos security evidence --period current --json
   ```
7. For AI/school/FCRA boundary review, collect the governance packet:
   ```bash
   complyos governance packet --lane campus --json
   ```
8. For privacy/DSR work, create a tenant-scoped request and record controller approval before export or deletion:
   ```bash
   complyos privacy request <subject-id> --type access --json
   complyos privacy approve <request-id> --note "controller approved" --json
   ```
9. Before deletion, check legal-hold status through the delete workflow; deletion blocks on active holds:
   ```bash
   complyos privacy delete <request-id> --json
   ```

## AI rule

AI is proposal-only. You may use:

```bash
complyos ai propose-mapping UserID CourseID Status --json
```

You must not use AI output to mark compliance, promote imports, send remediation, or change rules. Approval records are metadata only.

## Privacy rule

Privacy workflows are operational support only, not legal conclusions. Use:

```bash
complyos privacy request <subject-id> --type access --json
complyos privacy approve <request-id> --note "controller approved" --json
complyos privacy export <request-id> --json
complyos privacy legal-hold <subject-id> --reason "..." --json
complyos privacy retention configure --raw-import-days 30 --evidence-days 2555 --action-log-days 2555 --ai-proposal-days 180 --privacy-request-days 365 --json
complyos privacy retention run --dry-run --json
```

Do not bypass tenant-scoped requests or approval records. Do not delete if a legal hold is active; tenant-level holds also block retention purges for raw imports, AI proposals, evidence, and action logs. Final legal judgment still lives outside the tool.

## Claims rule

Say readiness/control mapping. Do not make legal or certification claims unless a reviewed artifact authorizes the exact language.

## Surface preference

- Local operator: CLI.
- Agent automation: MCP tools with scoped service-account context.
- Product/API integration: `/api/v1` routes.
- UI: enterprise shell once implemented; do not treat the landing page as the product.
