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
   complyos evidence list --json
   ```

## AI rule

AI is proposal-only. You may use:

```bash
complyos ai propose-mapping UserID CourseID Status --json
```

You must not use AI output to mark compliance, promote imports, send remediation, or change rules. Approval records are metadata only.

## Claims rule

Say readiness/control mapping. Do not make legal or certification claims unless a reviewed artifact authorizes the exact language.

## Surface preference

- Local operator: CLI.
- Agent automation: MCP tools with scoped service-account context.
- Product/API integration: `/api/v1` routes.
- UI: enterprise shell once implemented; do not treat the landing page as the product.
