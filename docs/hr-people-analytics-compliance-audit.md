# HR and people-analytics compliance audit

Date: 2026-06-12
Scope: ComplyOS as HR/L&D compliance operations software that connects to LMS/HRIS data, identifies training gaps, creates evidence trails, and may support schools.

## BLUF

ComplyOS should be positioned as **HR/L&D compliance operations and evidence automation**, not as accounting compliance and not as automated employment decision software.

Current repo posture: **early readiness / privacy, security-evidence, and governance packet foundations started**.

The strongest implemented areas are service-layer authorization, gated imports, evidence logging, AI proposal-only workflows, readiness guardrails, the Phase A privacy artifact set, approval-gated DSR workflows, legal-hold blocking, retention cleanup for closed privacy cases, terminal raw-import payloads, rejected/expired AI proposals, evidence ledger entries, and action logs, readiness-only security evidence packet, security operations procedures, and AI/school/FCRA governance packet. The biggest remaining gaps are production security receipts, executed customer contracts, backup lifecycle evidence, immutable audit storage, and production scheduling, school/customer paperwork review, formal auditor evidence, and external HR/AI legal review.

## What compliance categories apply

| Category | Applies now? | Why it matters | Current posture |
|---|---:|---|---|
| Vendor security assurance: SOC 2 Type II, later ISO 27001 | Yes for enterprise buyers | Customers will treat HR/LMS data as sensitive workforce data. SOC 2 is not accounting-only; it is a vendor trust report. | Partial readiness only |
| Privacy: GDPR, UK GDPR, CCPA/CPRA, state privacy laws, global privacy equivalents | Yes if personal data is processed | Employee, learner, student, and admin records are personal data. | Partial technical controls; missing legal/program artifacts |
| HR / employment law guardrails: EEOC, ADA, adverse impact | Conditional | Applies if outputs influence hiring, promotion, discipline, termination, compensation, or opportunity allocation. | Product should avoid automated employment decisions |
| AI governance: EU AI Act, NYC AEDT rules, Colorado AI Act, similar laws | Conditional / likely if AI affects people decisions | HR, worker management, education, and vocational training AI can become high-risk. | Proposal-only AI and impact-assessment packet exist; external review missing |
| Education privacy: FERPA, COPPA, state student privacy, accessibility | Conditional | Applies when selling to schools or processing student records. | Readiness packet exists; school-specific terms and accessibility audit missing |
| FCRA / background screening | Avoid unless intentionally entering screening | Trigger risk if reports are used for employment eligibility/background-style decisions. | Boundary artifact exists; needs contract/sales enforcement |
| Accessibility: WCAG, ADA, Section 508/public-sector procurement | Likely for schools/government and good enterprise procurement | Buyer reviews often require accessible admin tools and reports. | Packet exists; real audit/VPAT evidence missing |

## What is not the primary compliance lane

- SOC 1: not first-priority unless ComplyOS becomes relevant to financial reporting controls.
- SOX: not first-priority unless ComplyOS becomes part of a public-company financial control process.
- PCI DSS: not applicable unless ComplyOS stores or processes payment-card data.
- HIPAA: not applicable for generic HR/L&D data; may apply only if ComplyOS processes PHI for covered entities/business associates.
- Accounting compliance: not the product category.

## Product boundary that keeps risk manageable

Safe line:

> ComplyOS identifies training gaps, tracks evidence, prepares audit packets, routes review workflows, and keeps AI proposal-only.

Danger line:

> ComplyOS decides who gets hired, fired, promoted, disciplined, ranked, compensated, or denied opportunity.

The repo already supports the safer line through import quarantine/promotion, actor permissions, evidence logging, readiness language, and AI proposal-only behavior. It does not yet contain enough legal/program controls for the dangerous line.

## Current implementation evidence

| Control area | Repo evidence | Audit readout |
|---|---|---|
| Service authorization | `complyos/services/context.py`; `tests/unit/test_authz.py` | Designed. Roles and permissions exist and fail closed in services. |
| Import data integrity | `complyos/services/imports.py`; `tests/unit/test_import_service.py`; `tests/unit/test_api_v1.py` | Designed. Preview/quarantine/decision/promotion path exists. API rejects server-side import paths. |
| Audit/evidence logging | `complyos/core/repository.py`; `complyos/models/database.py`; `complyos/services/imports.py` | Partial. Tenant-scoped evidence/action logs and retention cleanup exist; export packaging, immutable storage, production scheduling, and review cadence are not productionized. |
| AI proposal-only | `complyos/services/ai_proposals.py`; `tests/unit/test_ai_proposals.py`; `tests/unit/test_mcp_enterprise.py` | Designed. AI mapping suggestions are metadata/proposals until approval. |
| API/MCP/CLI surfaces | `complyos/web/api_v1.py`; `complyos/api/mcp_server.py`; `complyos/cli.py`; `docs/agent-surface.md` | Designed for local/dev and agent operation. Production auth and service-account model still need hardening. |
| Readiness guardrails | `complyos/services/readiness.py`; `docs/compliance-readiness.md`; `tests/unit/test_no_false_compliance_claims.py` | Designed. Unsupported claims are blocked in public docs. |
| Privacy program artifacts | `docs/privacy-data-map.md`; `docs/data-retention-deletion-policy.md`; `docs/data-subject-request-workflow.md`; `docs/subprocessors.md`; `docs/dpa-template.md`; `complyos/services/privacy.py` | Partial. Phase A artifacts, approval-gated DSR workflows, legal-hold blocking, and retention cleanup for closed privacy cases, terminal raw imports, rejected/expired AI proposals, evidence ledger entries, and action logs exist; they still need counsel review, production evidence, backup lifecycle evidence, scheduling, and customer support/SLA operations. |
| Security policy | `SECURITY.md`; `docs/breach-response-runbook.md`; `docs/security-evidence-control-matrix.md`; `docs/access-review-procedure.md`; `docs/vulnerability-management-program.md`; `docs/backup-restore-dr-plan.md`; `docs/incident-tabletop-template.md`; `complyos/services/security_evidence.py` | Partial. Reporting, secret handling, breach-response workflow, readiness-only evidence packet, and security-ops procedures exist; production access-review, scan, backup/restore, monitoring, tabletop, and DR receipts are still external evidence work. |
| Governance packet | `docs/ai-governance-impact-assessment.md`; `docs/school-vendor-privacy-accessibility-packet.md`; `docs/fcra-employment-decision-boundary.md`; `complyos/services/governance.py` | Partial. AI/school/accessibility/FCRA boundaries are packetized with CLI/API/MCP; counsel, customer terms, and real accessibility evidence remain external. |
| Education readiness | `docs/compliance-readiness.md`; `docs/data-subject-request-workflow.md`; `docs/dpa-template.md`; `docs/school-vendor-privacy-accessibility-packet.md` | Partial. FERPA/COPPA/accessibility are packetized and routed into DSR/DPA placeholders, but school-specific terms, deletion proof, and COPPA age/consent handling still need customer/counsel review. |

## Gap audit by compliance lane

### 1. Vendor security assurance: SOC 2 Type II readiness

Current distance: **medium-high gap**.

What exists:
- Service-layer permissions.
- Action/evidence tables.
- Release checklist.
- Security policy.
- Tests and CI.

Missing before serious enterprise procurement:
- Defined SOC 2 scope and control owners.
- Production environment diagram and data flow.
- Formal access review process.
- SSO/SAML and SCIM or documented customer identity strategy.
- Tenant isolation evidence.
- Encryption-at-rest and encryption-in-transit evidence.
- Logging/monitoring/alerting evidence.
- Vulnerability management and dependency review cadence.
- Incident response runbook and tabletop evidence.
- Backup/restore and disaster recovery evidence.
- Vendor/subprocessor risk review.
- Change-management evidence over time.
- External auditor engagement for Type I/Type II.

Practical next milestone:
- Build a SOC 2 evidence room and run a Type I readiness review before claiming audit readiness.

### 2. Privacy: GDPR, UK GDPR, CCPA/CPRA, global privacy

Current distance: **medium-high gap**.

What exists:
- Data minimization direction in import flow.
- Evidence hashing.
- Readiness docs and forbidden-claim tests.
- Actor context and tenant IDs.
- Phase A data map, retention/deletion policy, DSR workflow, DPA template, subprocessor register, and DSR/retention/legal-hold service primitives.
- Dry-run/apply retention cleanup for closed privacy cases, terminal raw import rows/decisions, old rejected/expired AI proposals, tenant evidence entries, and tenant action logs.

Missing:
- Production-approved data map / RoPA with customer-specific regions, subprocessors, and retention.
- Lawful-basis analysis for customer, employee, learner, and student data.
- Privacy notice language.
- Counsel-approved DPA template and customer-ready privacy terms.
- Approved production subprocessor list.
- Backup lifecycle evidence, production retention scheduling, and immutable audit storage controls.
- Production DSR queue operations and customer-specific SLA handling.
- Tested breach notification workflow and tabletop evidence.
- International transfer mechanism: SCCs, UK IDTA/addendum, transfer impact assessment where needed.
- DPIA / privacy impact assessment template for high-risk processing.
- Customer configuration for data-region and retention.

Practical next milestone:
- Wire the existing retention cleanup into scheduled operations, then complete backup lifecycle evidence and customer-specific schedules before selling to regulated buyers.

### 3. HR / employment law and people analytics

Current distance: **medium gap if product stays training-evidence-only; high gap if product makes people decisions**.

What exists:
- Current language and services can support training gap evidence without ranking or discipline.
- AI is proposal-only.

Missing:
- Explicit product policy: no automated hiring, promotion, discipline, termination, compensation, or opportunity decisions.
- Human-review requirement for any action affecting an employee/student.
- Customer-facing explanation of outputs and limitations.
- Bias/adverse-impact assessment framework if outputs are used in employment decisions.
- Accommodation workflow notes for ADA/disability-related issues.
- Protected-class data handling rules: generally do not collect unless legally required and controlled.

Practical next milestone:
- Add an “employment decision boundary” policy to product docs and UI/API output language.

### 4. AI governance

Current distance: **medium-high gap**.

What exists:
- Proposal-only AI mapping service.
- Provenance fields for AI proposals.
- Approval endpoint/tooling.

Missing:
- AI system inventory.
- Model/provider register.
- Human oversight policy.
- Prompt/input/output logging policy.
- AI risk classification for HR, worker management, education, and vocational training contexts.
- AI impact assessment template.
- Bias testing plan if AI ever influences consequential decisions.
- Customer notice language when AI is used.
- Appeal/contest/escalation process for affected people if product crosses into decision support.

Practical next milestone:
- Keep AI limited to metadata/proposals and add an AI use policy plus impact-assessment template.

### 5. Education and school readiness

Current distance: **high gap for direct school sales; medium if selling only to companies**.

What exists:
- Campus profile direction.
- FERPA/COPPA/accessibility readiness notes.

Missing:
- FERPA school-official contract language.
- Student data privacy agreement template.
- Data minimization and deletion commitments for school records.
- Parent/student request flow where applicable.
- COPPA review for under-13 processing.
- Accessibility audit and VPAT/ACR if public-sector or school procurement expects it.
- State student privacy law review by target state.

Practical next milestone:
- Decide whether K-12, higher-ed, or enterprise workforce is the first sales lane. K-12 adds the most paperwork.

### 6. FCRA / background screening

Current distance: **not applicable if avoided; very high gap if entered**.

What exists:
- Nothing indicating ComplyOS is a background screening or employment eligibility reporting product.

Required guardrail:
- Do not market reports as employment eligibility/background reports.
- Do not provide recommendations that resemble employment screening decisions.
- If customers use ComplyOS for employment decisions anyway, require legal review and product-contract limitations.

Practical next milestone:
- Add a “not a background screening / FCRA consumer report” product boundary if sales copy could be misunderstood.

### 7. Accessibility

Current distance: **medium gap**.

What exists:
- Static/public surfaces and dashboards, but no systematic accessibility evidence in this audit.

Missing:
- WCAG 2.2 AA audit for web UI and generated reports.
- Keyboard navigation and screen-reader checks.
- Color contrast evidence.
- Accessible table/report exports.
- VPAT/ACR if selling to schools/government/public sector.

Practical next milestone:
- Add an accessibility test/audit pass for dashboard, report, and landing page.

## Readiness scorecard

| Lane | Current score | Meaning |
|---|---:|---|
| Training-gap evidence workflow | 70% | Good product-core direction; needs production hardening. |
| Service authorization and audit trail | 55% | Designed, partially implemented, not yet production-certified. |
| SOC 2 enterprise security | 48% | Readiness inventory, breach runbook, evidence packet, and security-ops procedures exist; production control receipts and third-party auditor evidence still missing. |
| GDPR/CCPA privacy program | 64% | Phase A artifacts, approval-gated DSR services, legal holds, and first retention cleanup across privacy cases/raw imports/rejected AI proposals/evidence/logs exist; counsel review, production evidence, scheduled jobs, and backup lifecycle evidence still missing. |
| HR employment-law decision guardrails | 48% | Product boundary and governance packet exist; needs contract/sales enforcement and counsel review. |
| AI governance | 48% | Proposal-only code and impact-assessment packet exist; formal reviewed risk program missing. |
| School/FERPA/COPPA readiness | 46% | Direction, DPA/DSR placeholders, privacy workflows, and school-vendor packet exist; school-specific terms and procurement evidence missing. |
| Accessibility procurement readiness | 32% | Procurement packet exists; needs real audit and VPAT/ACR evidence. |
| FCRA/background-screening readiness | 35% | Boundary artifact exists; should remain out of scope unless intentionally built. |

Overall: **about 64% toward enterprise HR/school compliance readiness**.

That does not mean the code is bad. It means enterprise compliance is mostly evidence, contracts, procedures, production controls, and reviewed claims — not just application code.

## Ordered remediation roadmap

### Phase A — Product boundary and privacy foundation

1. Add product boundary language: not employment decisioning, not background screening, no automated discipline. **Started with explicit FCRA/employment-decision boundary.**
2. Create data map / RoPA for HRIS, LMS, CSV, API, MCP, reports, evidence ledger. **Started.**
3. Create retention and deletion policy. **Started.**
4. Create DSR workflow: access, export, correction, deletion, objection/restriction where applicable. **Started.**
5. Create subprocessor list and DPA template. **Started.**
6. Create breach response procedure. **Started.**
7. Implement these workflows in code. **Started: DSR cases, controller approval, subject export/delete, retention metadata, legal holds, closed-case cleanup, terminal raw-import cleanup, rejected/expired AI-proposal cleanup, evidence cleanup, and action-log cleanup now exist.**
8. Add backup lifecycle evidence, production DSR queue operations, scheduled jobs, immutable audit controls, and counsel/security review. **Remaining.**

### Phase B — Production security and SOC 2 readiness

1. Define SOC 2 scope and control matrix.
2. Add SSO/SAML/SCIM plan or documented auth strategy.
3. Add tenant isolation evidence and tests.
4. Add audit-log retention and tamper-resistance plan.
5. Add vulnerability management cadence and dependency scan evidence. **Procedure started; scan receipts remain.**
6. Add access review procedure. **Started; quarterly export/signoff receipts remain.**
7. Add incident response tabletop template. **Started; completed exercise evidence remains.**
8. Build evidence-room folder structure.

### Phase C — AI and HR risk controls

1. Create AI system inventory. **Started through governance packet.**
2. Create AI impact assessment template. **Started.**
3. Keep AI proposal-only in code and docs. **Started.**
4. Add customer notices for AI-assisted mapping.
5. Add human-review and appeal/escalation policy if any output affects people.
6. Add bias/adverse-impact audit plan before any ranking/scoring/decisioning feature.

### Phase D — School lane, only if chosen

1. Create FERPA school-official/customer-contract language. **Started as checklist; still needs counsel/customer terms.**
2. Create student data privacy agreement template. **Not yet.**
3. Add school deletion/export procedures. **Started via DSR workflow; needs school-specific review.**
4. Review COPPA if under-13 data is in scope. **Started as checklist; still needs target-customer facts.**
5. Complete WCAG 2.2 AA audit and VPAT/ACR plan. **Packet started; real audit remains.**

## Claim language

Allowed:
- “SOC 2 readiness controls in progress.”
- “GDPR/CCPA readiness support.”
- “Evidence-backed audit trail.”
- “Human-reviewed AI proposals.”
- “Designed to support HR/L&D compliance operations.”

Not allowed without counsel/auditor approval:
- “Certified under SOC 2.”
- “Meets SOC 2 requirements.”
- “Meets GDPR requirements.”
- “Meets FERPA requirements.”
- “Meets COPPA requirements.”
- “Automated employment decisioning.”
- “Bias-free AI.”
- “Legal compliance guaranteed.”

## Source anchors for legal review

These links are source anchors for counsel/auditor review, not legal advice:

- AICPA SOC suite: https://www.aicpa-cima.com/resources/landing/system-and-organization-controls-soc-suite-of-services
- EU GDPR text: https://eur-lex.europa.eu/eli/reg/2016/679/oj/eng
- California CCPA/CPRA overview: https://oag.ca.gov/privacy/ccpa
- EEOC AI and ADA resources: https://www.eeoc.gov/eeoc-disability-related-resources/artificial-intelligence-and-ada
- FTC FCRA employment screening guidance: https://www.ftc.gov/business-guidance/resources/what-employment-background-screening-companies-need-know-about-fair-credit-reporting-act
- EU AI Act overview: https://digital-strategy.ec.europa.eu/en/policies/regulatory-framework-ai
- EU AI Act Annex III high-risk areas: https://ai-act-service-desk.ec.europa.eu/en/ai-act/annex-3
- NYC Automated Employment Decision Tools: https://www.nyc.gov/site/dca/about/automated-employment-decision-tools.page
- Colorado SB24-205: https://leg.colorado.gov/bills/sb24-205
- FERPA overview: https://studentprivacy.ed.gov/ferpa
- WCAG 2.2: https://www.w3.org/TR/WCAG22/
