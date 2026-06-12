# ComplyOS readiness controls

This document is not legal advice and is not a certification statement. It defines product controls, artifacts, and review gates for company and school buyers.

## BLUF

ComplyOS should present itself as readiness/control-mapping software until counsel, auditors, and customer contracts approve stronger language.

## Control families

| Family | What ComplyOS must prove | First artifact |
|---|---|---|
| Access control | Actor context, roles, permissions, tenant boundary checks | `complyos/services/context.py` |
| Evidence integrity | Source hashes, transformation steps, output hashes | `evidence_ledger` table and `complyos evidence list` |
| Import governance | Preview, quarantine, row decisions, blocked promotion | `complyos/services/imports.py` |
| AI governance | Proposal-only outputs, provenance, human approval | `complyos/services/ai_proposals.py` |
| Change management | Release checklist, test gates, review evidence | `docs/release-checklist.md` |
| Incident response | Security contact, triage path, severity model | `SECURITY.md` |
| Accessibility | WCAG 2.2 AA target and public-sector expectations | future shell a11y test evidence |
| School privacy | FERPA/COPPA review inputs, minimization, access logs | this doc plus contract review |
| Global privacy | Purpose, minimization, retention, data-region and subprocessor records | readiness service metadata |

## SOC 2 readiness posture

AICPA Trust Services Criteria cover Security, Availability, Processing Integrity, Confidentiality, and Privacy. The first product posture should focus on Security, Confidentiality, Availability, and Processing Integrity because ComplyOS transforms learning records into audit outputs.

Product requirements:

- service-layer authz tests;
- actor/action/object/result logs;
- deterministic audit engine with evidence hashes;
- backup/restore procedure for local/customer-hosted deployments;
- release/change-management checklist;
- incident response runbook;
- vendor/model governance for any external AI provider.

Reference: AICPA Trust Services Criteria resource: https://www.aicpa-cima.com/resources/download/2017-trust-services-criteria-with-revised-points-of-focus-2022

## School readiness posture

School deployments need stricter defaults:

- minimize imported student/learner fields;
- expose unnecessary columns in import preview;
- keep AI headers-only unless a reviewed contract allows record processing;
- separate student-record visibility by role;
- keep audit/action logs for record access and export;
- target WCAG 2.2 AA for web shell workflows.

References:

- FTC COPPA FAQ: https://www.ftc.gov/business-guidance/resources/complying-coppa-frequently-asked-questions
- W3C WCAG 2.2: https://www.w3.org/TR/WCAG22/
- DOJ ADA web/mobile rule fact sheet: https://www.ada.gov/resources/2024-03-08-web-rule/
- 1EdTech LTI: https://www.1edtech.org/standards/lti
- 1EdTech OneRoster: https://www.1edtech.org/standards/oneroster
- 1EdTech Caliper: https://www.1edtech.org/standards/caliper

## Global privacy readiness

Global privacy posture must be a regional control matrix, not a badge. Store and review these fields per tenant/source/import before hosted or cross-border deployments:

- data region;
- processing purpose;
- data categories;
- retention policy;
- subprocessors and model providers;
- export destinations;
- incident owner and notification workflow;
- privacy request runbook for access, correction, deletion, export, restriction/objection where applicable.

Watchlist references:

- EU GDPR text: https://eur-lex.europa.eu/eli/reg/2016/679/oj
- EU AI Act text: https://eur-lex.europa.eu/eli/reg/2024/1689/oj
- UK ICO guidance hub: https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/
- Brazil LGPD: https://www.gov.br/anpd/pt-br/centrais-de-conteudo/outros-documentos-e-publicacoes-institucionais/lgpd-en-lei-no-13-709-capa.pdf
- Canada PIPEDA: https://laws-lois.justice.gc.ca/eng/acts/p-8.6/
- Australia Privacy Act/OAIC: https://www.oaic.gov.au/privacy/privacy-legislation/the-privacy-act
- Singapore PDPA: https://www.pdpc.gov.sg/overview-of-pdpa/the-legislation/personal-data-protection-act
- Japan APPI/PPC legal hub: https://www.ppc.go.jp/en/legal/
- India DPDP framework: https://www.meity.gov.in/data-protection-framework
- South Africa POPIA regulator hub: https://inforegulator.org.za/popia/

## Claim guardrail

Public copy must stay in this lane:

- okay: readiness, control mapping, evidence-backed audit trail, designed for auditor/counsel review;
- not okay: certification/legal-status claims unless a reviewed artifact explicitly authorizes the exact wording.
