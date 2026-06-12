# ComplyOS subprocessors

Status: readiness artifact, not legal advice.
Owner: privacy/security/vendor management.
Review cadence: before production launch, before adding a vendor, and quarterly.

## Subprocessor register

No production subprocessors approved.

| Subprocessor | Purpose | Data categories | Region | Status | Notes |
|---|---|---|---|---|---|
| TBD hosting provider | application hosting | tenant data, logs, backups | TBD | not approved | Select before hosted production. |
| TBD database/backups | persistence and restore | tenant data, evidence, logs | TBD | not approved | Must support encryption and deletion lifecycle. |
| TBD email/notification provider | notifications | recipient, message metadata | TBD | not approved | Avoid unnecessary personal data in message body. |
| TBD AI/model provider | optional mapping proposals | headers/metadata only by default | TBD | not approved | Do not send row-level personal data without approval. |
| TBD observability provider | logs/metrics/traces | security and operational metadata | TBD | not approved | Scrub secrets and minimize personal data. |

## Review cadence

Before approval, each subprocessor needs:

- security review;
- privacy/data transfer review;
- DPA or equivalent contract;
- region and data residency review;
- deletion/return support review;
- breach notice obligation review;
- customer notice requirement review.

## Customer notice

ComplyOS should publish and version this register before hosted production use. Customer notice should include:

- new subprocessor name;
- purpose;
- data categories affected;
- region;
- effective date;
- objection/escalation path if contract provides one.

## Approval status values

- not approved;
- security review pending;
- privacy review pending;
- contract pending;
- approved for development only;
- approved for production.

## Implementation gaps

- Decide production hosting stack.
- Add vendor security questionnaire records.
- Add customer notice process.
- Link subprocessors to the data map and DPA.
