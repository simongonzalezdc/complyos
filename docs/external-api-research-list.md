# External API Research List

We are **not** building against these external APIs right now. This file is only
the research/acquisition list so access decisions do not block production
hardening.

## Regulatory/source intelligence APIs

| Priority | API/source | Access question to research | Why we may need it | Official starting point |
| --- | --- | --- | --- | --- |
| 1 | Federal Register API | Confirm commercial monitoring terms, rate limits, pagination behavior. | US federal proposed/final rules and agency metadata. | https://www.federalregister.gov/developers/documentation/api/v1 |
| 1 | eCFR API | Confirm supported search/full-section endpoints and historical/diff usage. | Current/historical CFR text and codified requirements. | https://www.ecfr.gov/developers/documentation/api/v1 |
| 1 | Regulations.gov API | Get API key; confirm rate limits, commercial use, docket/comment access. | Proposed-rule dockets and supporting material before final rules. | https://open.gsa.gov/api/regulationsgov/ |
| 2 | GovInfo API | Get api.data.gov key; confirm package/PDF/XML retrieval needs. | Official US government publication packages and source PDFs. | https://api.govinfo.gov/docs/ |
| 2 | EUR-Lex web services | Register; confirm SOAP limits, CELEX coverage, commercial terms. | EU regulations/directives for global clients. | https://eur-lex.europa.eu/content/tools/web-services.html |
| 2 | OSHA laws/regulations pages | Confirm crawl/scrape terms and stable page/PDF structure. | Workplace safety and training obligations. | https://www.osha.gov/laws-regs |
| 2 | California DIR/DLSE pages | Confirm crawl/scrape terms and state update patterns. | California labor/employment training changes. | https://www.dir.ca.gov/dlse/ |
| 3 | EEOC guidance/laws pages | Confirm crawl/scrape terms and update feeds. | Harassment, discrimination, accommodation, manager training relevance. | https://www.eeoc.gov/laws/guidance |
| 3 | DOL/WHD pages | Confirm crawl/scrape terms and update feeds. | Wage/hour and employment compliance training relevance. | https://www.dol.gov/agencies/whd |
| 3 | US Department of Education / Student Privacy | Confirm APIs/feeds for FERPA/privacy guidance. | Campus/school readiness flows. | https://studentprivacy.ed.gov/ |

## LMS / HRIS / productivity APIs

| Priority | System/API | Access question to research | Why we may need it |
| --- | --- | --- | --- |
| 1 | Workday APIs | Customer tenant, OAuth/API permissions, data scopes, sandbox access. | HRIS roster, worker attributes, org/manager context. |
| 1 | SAP SuccessFactors OData APIs | Customer tenant, API user, OAuth/SAML setup, LMS module availability. | HRIS/LMS records for enterprise buyers. |
| 1 | Cornerstone OnDemand APIs | Customer tenant, OAuth/API permissions, completion/assignment endpoints. | Enterprise LMS assignments, completions, transcripts. |
| 1 | Canvas LMS API | Developer key/institution approval, enrollment/completion/activity endpoints. | Higher-ed LMS data. |
| 2 | Moodle Web Services API | Site token, service enablement, role permissions. | Schools/smaller training teams. |
| 2 | Blackboard Learn REST API | Developer app/institution approval, gradebook/course endpoints. | Higher-ed LMS path. |
| 2 | D2L Brightspace Valence API | OAuth app/institution approval, enrollment/completion endpoints. | Higher-ed/corporate LMS path. |
| 2 | Microsoft Graph | Tenant admin consent, Teams/calendar/user scopes. | Training scheduling, reminders, roster context. |
| 2 | Google Workspace/Classroom APIs | OAuth scopes/admin consent. | School/team scheduling and learner data. |

## Decision rule

Do not let these block internal product hardening. Build internal contracts,
review queues, RBAC, persistence, audit logs, scheduling hooks, and UI/API flows
against fixture/local/public-free data first. Add external APIs behind those
contracts later.
