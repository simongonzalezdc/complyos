# ComplyOS agent surface map

Status: enterprise-remediation draft. This is an operator map, not a marketing page.

## Rule zero

Agents must use the same service-backed workflows as humans. No MCP-only shortcut may mutate tenant data.

## Surface matrix

| Job | Preferred surface | Command / tool | Permission | Guardrail |
|---|---|---|---|---|
| Check readiness | CLI or MCP | `complyos readiness --json`; `check_readiness` | `readiness:read` | Readiness-only. No legal/certification claims. |
| Preview CSV import | CLI/API/MCP | `complyos import preview file.csv --json`; `POST /api/v1/imports/preview`; `preview_import_batch` | `import:preview` | Does not mutate active records. Review issues first. |
| Promote import | CLI/API/MCP | `complyos import promote <batch>`; `POST /api/v1/imports/{id}/promote`; `promote_import_batch` | `import:promote` | Blocked unless every row is valid or ignored. Evidence log required. |
| Read evidence | CLI/API/MCP | `complyos evidence list --json`; `GET /api/v1/evidence`; `list_evidence_ledger` | `evidence:read` | Cite hashes in summaries. |
| AI field mapping | CLI/API/MCP | `complyos ai propose-mapping ...`; `POST /api/v1/ai/proposals/mapping`; `propose_field_mapping` | `ai:propose` | Proposal-only. Headers-only default. |
| Approve AI proposal | CLI/API/MCP | `complyos ai approve <proposal>`; `POST /api/v1/ai/proposals/{id}/approve`; `approve_ai_proposal` | `ai:approve` | Metadata approval only; does not change compliance truth. |
| Audit gaps | CLI/MCP | `complyos audit --json`; `audit_compliance_gaps` | `audit:run` | Use deterministic audit output and evidence hash. |
| Connector health | CLI/MCP | `complyos health`; `check_connector_health` | `connectors:read` | Do not leak credentials. |

## Agent operating sequence

1. Run readiness first for enterprise/customer-facing work.
2. Preview imports before any promotion.
3. Stop on `REJECTED`, `NEEDS_DECISION`, or `PENDING` rows.
4. If using AI mapping, keep it proposal-only and store provenance.
5. Cite evidence hashes and batch IDs in user-facing summaries.
6. Do not say the product has achieved legal/certification status. Say readiness/control mapping until reviewed artifacts exist.

## Production auth posture

- Local CLI uses explicit local-admin context.
- API v1 is context-backed. Set `COMPLYOS_API_TOKEN` for token auth in server use.
- Remote MCP should run as a scoped service account. Do not grant `admin:manage` by default.
- Mutating surfaces must go through service-layer permissions.

## Current API v1 endpoints

- `GET /api/v1/health`
- `GET /api/v1/readiness`
- `POST /api/v1/imports/preview`
- `POST /api/v1/imports/{batch_id}/decisions`
- `POST /api/v1/imports/{batch_id}/promote`
- `GET /api/v1/evidence`
- `POST /api/v1/ai/proposals/mapping`
- `POST /api/v1/ai/proposals/{proposal_id}/approve`
