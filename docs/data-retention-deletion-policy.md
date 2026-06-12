# ComplyOS data retention and deletion policy

Status: readiness artifact, not legal advice.
Owner: product/security + privacy/legal review.
Review cadence: quarterly and before customer contract signature.

## Purpose

This policy defines the baseline retention schedule and Deletion workflow for ComplyOS HR/L&D evidence automation data. Final retention must be controlled by customer contract, applicable law, and legal hold state.

## Retention principles

1. Keep only data needed for training compliance, evidence, security, customer support, and contractual audit windows.
2. Prefer normalized records and evidence hashes over raw exports.
3. Separate active operational data from audit evidence.
4. Make retention tenant-configurable before production enterprise use.
5. Do not delete data under active legal hold or customer-approved investigation hold.

## Retention schedule

| Data class | Baseline retention | Deletion trigger | Notes |
|---|---:|---|---|
| Raw CSV/import row payloads and import decision payloads | 30-90 days after terminal import batch | successful promotion, rejection, expiry, failed promotion, or tenant request | Dry-run/apply cleanup purges row payloads and import decisions after the window unless tenant legal hold blocks it. |
| Import batch metadata and hashes | contract/audit window | tenant deletion or expiry | Keep batch ID, source, hash, status, and action/evidence logs after raw rows/decision payloads are purged. |
| Learning records | customer contract / requirement lifecycle | tenant deletion, individual correction/deletion, or expiry | Some records may need longer retention for regulated training. |
| Evidence ledger | customer contract / audit window | contract expiry unless legal hold applies | Hashes may be retained longer than raw payloads. |
| Action/audit logs | 1-7 years depending on buyer | contract expiry unless legal hold applies | Enterprise buyers often require log retention. |
| AI proposal metadata | 30-180 days for rejected/expired proposals; audit window for approved proposals | proposal rejection/expiry or tenant deletion | Cleanup purges old rejected/expired proposal output and provenance; approved proposals remain evidence until their audit window. |
| Closed privacy request cases | default 365 days, tenant-configurable | retention cleanup run after case closure | Dry-run before apply; active legal holds block cleanup. |
| Security logs | 90 days to 1 year | rolling expiration | Extend for incidents and enterprise contracts. |
| Backups | production backup window | backup rotation | Deletion from backups follows backup lifecycle unless restore occurs. |

## Deletion workflow

1. Receive request from customer admin, privacy contact, or approved internal workflow.
2. Identify tenant, subject, systems, request scope, and legal hold status.
3. Verify authority with the customer/controller where ComplyOS is a processor/service provider.
4. Search active application records: users, learning records, imports, evidence, action logs, reports.
5. Delete, anonymize, or restrict records according to contract and legal basis.
6. Record deletion evidence: request ID, actor, timestamp, affected systems, outcome, exceptions.
7. Notify customer of completion or exceptions.
8. Let backups age out unless contract requires special handling and infrastructure supports it.

## Legal hold

Legal hold pauses deletion for affected records. Legal hold state must record:

- tenant;
- scope;
- reason;
- approving authority;
- start date;
- review date;
- release date.

## Audit evidence

Deletion and retention actions should generate evidence without exposing unnecessary personal data:

- request ID;
- actor ID;
- tenant ID;
- data classes touched;
- counts, not raw rows where possible;
- timestamp;
- exceptions and reason.

## Implementation gaps

- Tenant-configurable retention settings exist for raw imports, evidence, action logs, AI proposals, and closed privacy request cases.
- Privacy export/delete CLI/API/MCP workflows exist with permission gates and controller approval gating.
- Legal-hold model and deletion-blocking tests exist.
- Retention cleanup can dry-run/apply eligible closed privacy request cases, terminal raw import rows/decisions, old rejected/expired AI proposals, tenant-scoped evidence ledger entries, and tenant-scoped action logs.
- Subject legal holds block subject-specific cleanup; tenant-level legal holds block tenant-wide retention purges.
- Remaining: backup lifecycle evidence, immutable audit storage, production job scheduling, and counsel/customer-specific retention schedules.
