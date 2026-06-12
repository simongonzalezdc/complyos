# ComplyOS data subject request workflow

Status: readiness artifact, not legal advice.
Owner: privacy/legal review + support/security.
Review cadence: quarterly and before entering a new region or school lane.

## Purpose

This workflow defines how ComplyOS should handle individual privacy requests for HR/L&D, people analytics, and school/student data.

ComplyOS will usually act as a processor/service provider for customer-controlled workforce or student records. End-user requests should generally be routed through the customer/controller unless contract terms say otherwise.

## Request types

- Access / Export
- Correction
- Deletion
- Restriction or objection where applicable
- Do-not-sell/share where applicable
- School/student record access through the education customer where applicable

## Intake

Collect:

- requester name and contact;
- tenant/customer;
- request type;
- affected identifiers, if safely provided;
- region/jurisdiction if known;
- whether the requester is employee, learner, student, parent/guardian, admin, or customer representative;
- deadline clock and routing owner.

## Identity verification

Verification must match request risk:

- Customer admin request: verify admin authority in customer account or signed support process.
- Employee/learner request: route to customer/controller for verification unless contract authorizes ComplyOS to verify.
- Student/parent request: route through school customer unless written contract permits direct handling.
- High-risk requests: require privacy/legal review before disclosure or deletion.

## Export

For approved Access / Export requests:

1. create a tenant-scoped request case;
2. record customer/controller approval after identity and authority checks;
3. identify source systems and ComplyOS records;
4. export only the requester’s records and relevant evidence metadata;
5. exclude other people’s personal data where possible;
6. include machine-readable format where contract/region requires;
7. log request ID, actor, timestamp, systems, and counts.

## Correction

For approved Correction requests:

1. identify whether ComplyOS or source LMS/HRIS is the system of record;
2. if source system owns the field, route correction there and resync;
3. if ComplyOS owns derived metadata, update with audit log;
4. preserve evidence of correction without over-retaining incorrect raw data.

## Deletion

For approved Deletion requests:

1. create a tenant-scoped request case;
2. record customer/controller approval after identity and authority checks;
3. check legal hold, regulatory retention, and customer contract constraints;
4. delete or anonymize active records where permitted;
5. retain minimal audit evidence where required;
6. let backups expire through lifecycle unless special handling is contractually required;
7. document exceptions.

## Escalation triggers

Escalate to privacy/legal review when:

- the request involves EU/UK data;
- the request involves student records;
- the request involves protected-class, disability, accommodation, or employment-decision context;
- the customer and requester disagree;
- deletion conflicts with regulatory/audit retention;
- breach, litigation, or legal hold may apply.

## Implementation gaps

- DSR case model exists for local/service-backed workflows.
- Export/delete service methods exist and require controller approval.
- Customer/controller approval tracking exists in CLI/API/MCP.
- Legal-hold blocking exists for deletion.
- Tests cover tenant isolation, approval gating, legal-hold blocking, and CLI/API/MCP parity.
- Remaining: counsel-approved templates, production identity-verification workflow, customer-specific SLAs, support queue integration, and production evidence storage.
