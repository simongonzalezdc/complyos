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
| Read evidence | CLI/API/MCP | `complyos evidence list --tenant <tenant> --json`; `GET /api/v1/evidence`; `list_evidence_ledger(tenant_id)` | `evidence:read` | Tenant-scoped; cite hashes in summaries. |
| AI field mapping | CLI/API/MCP | `complyos ai propose-mapping ...`; `POST /api/v1/ai/proposals/mapping`; `propose_field_mapping` | `ai:propose` | Proposal-only. Headers-only default. |
| Approve AI proposal | CLI/API/MCP | `complyos ai approve <proposal>`; `POST /api/v1/ai/proposals/{id}/approve`; `approve_ai_proposal` | `ai:approve` | Metadata approval only; does not change compliance truth. |
| Collect security evidence | CLI/API/MCP | `complyos security evidence --json`; `GET /api/v1/security/evidence`; `collect_security_evidence` | `security:evidence:read` | Readiness-only control map; attach real audit artifacts separately. |
| Collect governance packet | CLI/API/MCP | `complyos governance packet --lane campus --json`; `GET /api/v1/governance/packet`; `collect_governance_packet` | `governance:read` | Readiness-only AI/school/FCRA boundary packet; attach counsel-reviewed terms separately. |
| Create privacy request | CLI/API/MCP | `complyos privacy request <subject>`; `POST /api/v1/privacy/requests`; `create_privacy_request` | `privacy:request` | Tenant-scoped case opens as `PENDING_CONTROLLER_APPROVAL`. |
| Approve privacy request | CLI/API/MCP | `complyos privacy approve <request>`; `POST /api/v1/privacy/requests/{id}/approve`; `approve_privacy_request` | `privacy:approve` | Records customer/controller approval before export/delete. |
| Export privacy subject | CLI/API/MCP | `complyos privacy export <request>`; `POST /api/v1/privacy/requests/{id}/export`; `export_privacy_subject` | `privacy:export` | Tenant-scoped export; blocked until approval. Do not disclose other subjects. |
| Delete privacy subject | CLI/API/MCP | `complyos privacy delete <request>`; `POST /api/v1/privacy/requests/{id}/delete`; `delete_privacy_subject` | `privacy:delete` | Blocked until approval and blocked again on active legal hold; logs counts, not raw data. |
| Configure retention | CLI/API/MCP | `complyos privacy retention configure ...`; `POST /api/v1/privacy/retention-policy`; `configure_privacy_retention` | `privacy:retention:manage` | Tenant policy metadata for raw imports, AI proposals, evidence/logs, and closed privacy cases. |
| Run retention cleanup | CLI/API/MCP | `complyos privacy retention run --dry-run`; `POST /api/v1/privacy/retention-policy/run`; `run_privacy_retention` | `privacy:retention:manage` | Dry-run by default; apply deletes eligible closed privacy cases, terminal raw import rows/decisions, rejected/expired AI proposals, evidence entries, and action logs unless legal hold blocks them. |
| Manage legal hold | CLI/API/MCP | `complyos privacy legal-hold <subject>`; `POST /api/v1/privacy/legal-holds`; `create_legal_hold` | `legal_hold:manage` | Active holds block deletion. Release requires explicit command/tool. |
| Audit gaps | CLI/MCP | `complyos audit --json`; `audit_compliance_gaps` | `audit:run` | Use deterministic audit output and evidence hash. |
| Connector health | CLI/MCP | `complyos health`; `check_connector_health` | `connectors:read` | Do not leak credentials. |

## Agent operating sequence

1. Run readiness first for enterprise/customer-facing work.
2. Preview imports before any promotion.
3. Stop on `REJECTED`, `NEEDS_DECISION`, or `PENDING` rows.
4. If using AI mapping, keep it proposal-only and store provenance.
5. Cite evidence hashes and batch IDs in user-facing summaries.
6. For privacy requests, create a case first and record controller approval before export/delete.
7. Never delete if a legal hold is active; tenant-level holds also block retention purges.
8. Do not say the product has achieved legal/certification status. Say readiness/control mapping until reviewed artifacts exist.

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
- `GET /api/v1/security/evidence`
- `GET /api/v1/governance/packet`
- `POST /api/v1/privacy/requests`
- `POST /api/v1/privacy/requests/{request_id}/approve`
- `POST /api/v1/privacy/requests/{request_id}/export`
- `POST /api/v1/privacy/requests/{request_id}/delete`
- `POST /api/v1/privacy/legal-holds`
- `POST /api/v1/privacy/legal-holds/{hold_id}/release`
- `POST /api/v1/privacy/retention-policy`
- `POST /api/v1/privacy/retention-policy/run`
