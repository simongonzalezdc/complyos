# ComplyOS privacy data map

Status: readiness artifact, not legal advice.
Owner: product/security + privacy/legal review.
Review cadence: every release that changes data categories, source systems, subprocessors, regions, retention, or AI behavior.

## Purpose

This document maps the personal data ComplyOS expects to process for HR/L&D compliance operations, training-gap evidence, school readiness, and audit packet generation.

ComplyOS should process the minimum data required to answer:

1. who is in scope for a required training rule;
2. what course/training record exists;
3. what gap or exception exists;
4. what evidence packet supports the result;
5. who reviewed, approved, imported, or exported the evidence.

## Data categories

| Category | Examples | Sensitivity | Notes |
|---|---|---:|---|
| Workforce learner identity | employee ID, learner ID, name, work email, department, region, manager ID | personal data | Use customer-provided stable identifiers where possible. |
| Student/education identity | student ID, school email, course enrollment identifiers | student data | School lane requires separate FERPA/student privacy review. |
| Training content metadata | course ID, title, requirement tags, renewal period, policy mapping | operational | Avoid storing unnecessary course content. |
| Learning records | completion date, status, expiry date, score where provided, exemption flag, source-system hash | personal data | Scores can become sensitive if used for employment decisions. |
| Assignment and rule metadata | role, location, department, group, required course mapping | personal data when tied to a person | Keep rules explainable and reviewable. |
| Audit/evidence records | evidence hash, generated report metadata, action log, reviewer ID, request ID | operational + personal data | Retain enough to prove audit trail without retaining raw exports indefinitely. |
| Import quarantine payloads | normalized CSV rows, validation issues, row decisions | personal data | Delete or minimize raw import data after promotion/rejection window. |
| AI proposal metadata | headers, suggested mappings, model/provider, confidence/provenance | metadata | AI stays proposal-only and should not receive unnecessary row-level personal data. |
| Security/auth metadata | actor ID, role, tenant ID, IP/session metadata if deployed | personal data | Needed for audit/security, governed by retention policy. |

## Source systems

| Source system | Current status | Data received | Processing purposes | Notes |
|---|---|---|---|---|
| CSV export | Implemented | users, courses, enrollments, learning records | local import, validation, evidence generation | API imports must use provided CSV text, not server paths. |
| Workday | Implemented connector lane | workers, learning assignments/records where configured | workforce training compliance | Customer config determines final fields. |
| SAP SuccessFactors | Implemented connector lane | users/courses/learning records | workforce training compliance | Treat as HR/LMS personal data. |
| Cornerstone | Implemented connector lane | users/courses/learning records | workforce training compliance | Treat as LMS personal data. |
| Canvas / school LMS | Planned/roadmap | students, enrollments, course completions | school training/readiness evidence | Requires school privacy package before production use. |
| API v1 | Implemented local-first surface | customer-submitted import and AI proposal inputs | integration and automation | Requires production auth and tenant isolation evidence before hosted use. |
| MCP tools | Implemented agent surface | scoped tool requests and outputs | agent-assisted operations | Service-layer permissions must remain source of truth. |

## Processing purposes

| Purpose | Data needed | Must not do |
|---|---|---|
| Training gap audit | learner identity, course requirement, learning record status | Do not infer job performance or rank people. |
| Evidence packet generation | evidence ledger, hashes, report metadata, source-system references | Do not over-retain raw exports when hashes/normalized records are enough. |
| Import validation | CSV headers/rows, validation errors, reviewer decisions | Do not let AI or imports directly mutate truth without approval. |
| Connector sync | source-system records and stable IDs | Do not collect fields unrelated to training compliance. |
| AI field mapping | headers, target schema, proposal provenance | Do not send row-level personal data unless specifically approved. |
| Customer support/security | actor context, action logs, request IDs | Do not expose unrelated tenant data. |

## Retention

Default retention should be configurable by tenant and contract. Until customer-specific terms exist, use the data-retention/deletion policy as the working baseline:

- raw import files: short-lived quarantine window;
- normalized learning records: customer contract / regulatory need;
- evidence hashes and action logs: audit-window driven;
- AI proposal metadata: short-to-medium audit window;
- support/security logs: security-retention window;
- deleted tenants: remove or anonymize according to contract and legal hold state.

## Data subject rights

ComplyOS needs an operational workflow for:

- access/export requests;
- correction requests;
- deletion requests;
- restriction/objection requests where applicable;
- customer/controller approvals before acting on end-user requests;
- school/student record requests through the school customer where applicable.

See `docs/data-subject-request-workflow.md`.

## Regional transfer and residency notes

- Track where production data is stored, backed up, logged, and processed.
- Track subprocessors by region and purpose.
- For EU/UK data, evaluate SCCs, UK transfer addendum/IDTA, and transfer risk with counsel.
- Do not promise data residency until infrastructure and contract controls exist.

## Evidence to collect next

- Customer data-flow diagram.
- Field-level schema inventory for each connector.
- Production hosting/data-region record.
- Subprocessor list.
- Retention configuration evidence.
- Data export/deletion test evidence.
- Tenant isolation test evidence.
