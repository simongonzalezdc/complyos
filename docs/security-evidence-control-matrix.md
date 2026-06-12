# ComplyOS security evidence control matrix

Status: readiness artifact, not an audit report.
Owner: security/engineering + auditor review.
Review cadence: every release and every customer security review.

## Purpose

This matrix turns ComplyOS security readiness into an evidence packet that an auditor, buyer security team, or counsel can review. It does not assert certification or legal status.

## Runtime evidence packet

Use the shared service-backed surfaces:

```bash
complyos security evidence --period 2026-Q2 --json
```

API and MCP equivalents:

- `GET /api/v1/security/evidence?period=2026-Q2`
- `collect_security_evidence(period="2026-Q2")`

The packet is intentionally `readiness_only` and returns:

- control IDs;
- current readiness status;
- source/evidence references;
- evidence-task documents to complete with real receipts;
- gaps;
- next actions;
- action-log and evidence-ledger counts.

## Current control map

| Control ID | Area | Current status | Evidence refs | Remaining audit work |
|---|---|---|---|---|
| CC6.1 | logical access | partial | actor context, roles, authz tests, API token gate, `docs/access-review-procedure.md` | production SSO/MFA screenshots, access-review exports, joiner/mover/leaver tickets |
| CC7.2 | monitoring/audit logging | partial when logs exist | action log table, repository audit methods | production log sink, alerts, tamper-resistance evidence |
| CC7.3 | incident response | partial | `SECURITY.md`, breach-response runbook, `docs/incident-tabletop-template.md` | completed tabletop exercise and incident ticket examples |
| CC8.1 | change management | needs evidence | tests and git history | branch protection, review approvals, release checklist evidence |
| A1.2 | availability / backup / DR | partial | `docs/backup-restore-dr-plan.md` | backup job receipts, restore test, approved RTO/RPO |
| CC6.6 | vulnerability management | partial | `docs/vulnerability-management-program.md` | dependency/code scan output, remediation tickets, patch SLA evidence |
| P1.1 | privacy commitments | partial | privacy map, DSR workflow, privacy service | counsel-approved commitments and executed customer terms |

## Operating rule

Treat this as a collection aide. Before customer use, attach the real auditor/buyer artifacts: screenshots, tickets, scan outputs, access-review exports, restore-test receipts, incident/tabletop notes, release approvals, and signed terms.
