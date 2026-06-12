# ComplyOS Data Processing Addendum template

Status: working template for counsel review, not legal advice.
Owner: privacy/legal review.
Review cadence: before any customer signature and when entering a new region.

## Purpose

This Data Processing Addendum template captures the commercial/legal structure ComplyOS likely needs when processing HR/L&D, people analytics, or school data for customers.

Counsel must review before use.

## Parties and roles

- Customer: Controller or business, depending on region and contract.
- ComplyOS: Processor or service provider, depending on region and contract.
- End users: employees, contractors, learners, students, admins, or other customer-authorized users.

## Processing description

| Field | Draft position |
|---|---|
| Subject matter | HR/L&D compliance operations, training evidence, imports, reports, and audit trails. |
| Duration | Subscription term plus deletion/return period. |
| Processing purposes | Provide ComplyOS services, support, security, compliance evidence, and customer-authorized integrations. |
| Data categories | See `docs/privacy-data-map.md`. |
| Data subjects | Workforce learners, customer admins, school users/students where contracted. |
| Special category data | Not intentionally collected unless customer config requires it and a written addendum approves it. |

## Processor obligations

ComplyOS should commit to:

- process personal data only on documented customer instructions;
- implement Security measures appropriate for the data and risk;
- keep personnel confidentiality obligations;
- assist with Data subject rights where contractually required;
- assist with breach assessment and notifications;
- maintain subprocessor controls;
- return or delete data at termination, subject to legal hold and backup lifecycle;
- provide audit information reasonably required by the customer contract.

## Security measures

Baseline measures to attach as an exhibit:

- role-based access control;
- service-layer permission checks;
- tenant separation;
- encryption in transit;
- encryption at rest for hosted production;
- audit/action logging;
- vulnerability management;
- incident response process;
- backup and restore process;
- least-privilege access review;
- secure development and change management.

## Subprocessors

Subprocessors must be listed in `docs/subprocessors.md` and approved according to customer contract terms.

Required subprocessor terms:

- equivalent privacy/security obligations;
- breach notice support;
- deletion/return support;
- transfer mechanism support where applicable;
- audit/support obligations appropriate to service risk.

## International transfers

For EU/UK or similar transfer regimes, evaluate:

- SCCs;
- UK transfer addendum or IDTA;
- transfer impact assessment;
- region-specific supplemental terms;
- subprocessor transfer chain.

## Data subject rights support

ComplyOS should assist the customer/controller using `docs/data-subject-request-workflow.md`.

## Deletion and return

At termination or approved request:

- return/export available customer data where required;
- delete or anonymize active records;
- retain minimal evidence where legally/contractually allowed;
- let backups expire according to documented backup lifecycle unless otherwise required and supported.

## School data addendum placeholder

If selling to schools, add terms for:

- school-official/service-provider role;
- legitimate educational interest or equivalent contract framing;
- student data use restrictions;
- parent/student request routing;
- retention/deletion after contract;
- state student privacy law obligations;
- accessibility procurement exhibits.

## Open legal questions

- Exact controller/processor/business/service-provider role by customer and region.
- Whether any customer configuration introduces special category/sensitive data.
- Whether AI mapping metadata leaves the customer environment.
- Whether school deployments require separate student data privacy agreement.
- Whether cross-border transfers need supplemental controls.
