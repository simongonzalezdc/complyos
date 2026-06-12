# Source Intelligence API Inventory

This is the working research list for RegWatch and MicroLearn Radar source
monitoring. It separates what we can use now without paying from what needs a
key, registration, parser work, vendor approval, or later budget.

## Implemented without paid APIs

| Source/API | Status in repo | Auth/cost | What it gives us | Remaining work |
| --- | --- | --- | --- | --- |
| Federal Register API | `FederalRegisterClient` | Public/free; no key in current implementation. | Proposed/final rules, notices, agency metadata, document URLs, publication dates. | Tune agency/topic filters; add pagination; add exact effective/comment date extraction. |
| eCFR API | `ECFRClient` | Public/free; no key in current implementation. | Current/historical CFR search results, title/part/section metadata, text excerpts. | Validate endpoint parameters against production traffic; add full section fetch; add point-in-time diffing. |
| Local fixture/upload path | `source-intel run-fixture`, `source-intel run-upload`, and `SourceReviewStore` | Free/local. | Human-approved excerpts, text uploads, CSV/manual workflows, demo/proof runs when enterprise internet/API access is blocked. | Add structured CSV batch command for many approved source excerpts. |

## Free but not implemented yet

| Source/API | Auth/cost | Why we need it | Build notes |
| --- | --- | --- | --- |
| OSHA laws/regulations web pages | Public/free web pages. | Workplace safety and training obligations are core to the first RegWatch story. | Needs HTML/PDF parser, source-specific selectors, and canonical citation extraction. |
| California DIR/DLSE web pages | Public/free web pages. | California employment/labor training changes are commercially relevant. | Needs jurisdiction parser and manual coverage-gap rules. |
| State labor/civil-rights agency pages | Public/free varies by state. | Harassment prevention, wage/hour, safety, and employment-policy training often change at state level. | Needs source registry per state and parser profiles. |
| EEOC / DOL / HHS / ED official pages | Public/free web pages and feeds vary. | Federal HR, workplace, school, accessibility, and privacy guidance. | Prioritize by buyer vertical and source stability. |

## Keyed or registration-gated APIs to research

| Source/API | Gate | Why it matters | Decision needed |
| --- | --- | --- | --- |
| Regulations.gov API v4 | API key required for production use. | Dockets, proposed rules, comments, supporting material. Helps catch upcoming changes before final rules. | Get key, rate limits, terms, and whether commercial monitoring is allowed. |
| EUR-Lex web services | Free after registration; SOAP. | EU regulations/directives and CELEX metadata for global clients. | Register account, confirm usage limits, decide whether SOAP client is worth building now. |
| GovInfo API | API key. | Official US government publications, Federal Register/CFR PDFs and packages. | Decide if it is needed for authoritative PDF/package retrieval beyond Federal Register/eCFR. |
| GSA/Open data APIs beyond Regulations.gov | Usually key varies by API. | May help with federal procurement/vendor and agency metadata later. | Not critical for L&D v0 unless public-sector buyer appears. |

## LMS/HRIS/vendor APIs to research separately

These are not regulatory-source APIs, but they are needed for the full
LearningOps product.

| System | Gate | Why it matters |
| --- | --- | --- |
| Workday | Customer tenant + OAuth/API access. | HRIS roster, worker attributes, assignment context. |
| SAP SuccessFactors | Customer tenant + API permissions. | HRIS/LMS records for enterprise buyers. |
| Cornerstone OnDemand | Customer tenant + API permissions. | Large enterprise LMS completion and assignment data. |
| Canvas | Developer key / institution approval. | Higher-ed LMS enrollment/completion/activity data. |
| Moodle | Site token / web service enablement. | Schools and smaller training teams. |
| Blackboard Learn | Developer app + institution approval. | Higher-ed LMS path. |
| D2L Brightspace | OAuth app + institution approval. | Higher-ed/corporate LMS path. |
| Microsoft Graph | Tenant admin consent. | Teams/calendar/user data for training ops and reminders. |
| Google Workspace/Classroom | OAuth scopes/admin consent. | School/team scheduling and learner data where applicable. |

## No-paid operator commands now available

```bash
# List built-in free/source candidates and parser gaps
complyos source-intel sources --json

# Run a no-network fixture through RegWatch and MicroLearn adapters
complyos source-intel run-fixture --store source-intel-reviews.jsonl --json

# Dry-run the implemented live public clients without making network calls
complyos source-intel run-public --dry-run --json

# Run implemented free public clients live, if outbound network is allowed
complyos source-intel run-public --query training --store source-intel-reviews.jsonl --json

# Process an approved local text/source upload when APIs are blocked
complyos source-intel run-upload approved-guidance.txt --topic 'manager feedback' --store source-intel-reviews.jsonl --json

# Review or update the local proposal queue
complyos source-intel review --store source-intel-reviews.jsonl --json
complyos source-intel review --store source-intel-reviews.jsonl --proposal-id <id> --state approved_for_brief --json
```

## Guardrails

- No adapter auto-publishes training.
- No adapter mutates ComplyOS rules.
- Every proposal stays in a human-review queue first.
- Coverage gaps must be shown when a source has no parser, no results, or a failed fetch.
- Live crawler claims require scheduler/parser tests and operational evidence.
