# ComplyOS Context

## What ComplyOS Is

ComplyOS is a learning-compliance evidence engine. It ingests learning data from
CSV exports and LMS connectors, normalizes that data into one shared audit model,
and produces evidence-backed compliance gaps, audit trails, privacy workflows, retention cleanup, and readiness packets.

ComplyOS has two buyer tracks:

- **Workforce** — employee training compliance for L&D, People Ops, HRIS, and
  security compliance teams.
- **Campus** — student, program, district, and higher-ed requirement tracking for
  academic technology and compliance teams.

Both tracks use the same audit model. The terms differ by market, but the engine
still asks the same question: which learners lack valid evidence for required
learning items? The product should stay in the readiness/control-mapping lane until counsel, customers, and auditors approve stronger claims.

## Domain Glossary

| Term | Meaning |
|------|---------|
| **Learner** | The person whose learning compliance is audited. In Workforce this is usually an employee. In Campus this is usually a student. Current code stores learners as `User`. |
| **Learning Item** | The required learning object. It may be a course, module, training, assignment, certification, or requirement depending on the source system. Current code stores learning items as `Course`. |
| **Learning Record** | A normalized cross-LMS source record that says what happened between one learner and one learning item: assignment, enrollment, submission, completion, exemption, score, due date, or expiry. Current code has a `LearningRecord` model for connector normalization. |
| **Enrollment** | The current audit-engine compatibility model for a learner's relationship to a course. It is intentionally narrower than `LearningRecord`, but remains supported so the existing auditor and reports keep working. |
| **Compliance Gap** | A missing, incomplete, overdue, expired, or otherwise invalid requirement for a learner. Current code stores gaps as `ComplianceGap`. |
| **Evidence Ledger** | The tenant-scoped audit trail that hashes raw inputs, transformation steps, and audit outputs so reports can be defended later. Current code stores entries as `EvidenceLedgerEntry`. |
| **Privacy Request** | A tenant-scoped data-subject/privacy case. Export and deletion require recorded customer/controller approval. |
| **Legal Hold** | A subject or tenant-level hold that blocks deletion and retention cleanup until explicitly released. |
| **Retention Cleanup** | Dry-run/apply workflow for eligible closed privacy cases, terminal raw import payloads/decisions, rejected/expired AI proposals, evidence entries, and action logs. |
| **Security Evidence Packet** | A readiness-only packet mapping controls to evidence tasks and current receipts. It is not a SOC 2 report. |
| **Governance Packet** | A readiness-only AI/school/accessibility/FCRA boundary packet for review. |
| **Workforce** | The ComplyOS profile for employee learning-compliance operations. Typical source systems include Workday Learning, Cornerstone OnDemand, SAP SuccessFactors Learning, Docebo, Absorb, Litmos, and CSV exports. |
| **Campus** | The ComplyOS profile for education compliance operations. Typical source systems include Canvas, Brightspace, Blackboard, Moodle, Schoology, Google Classroom, and CSV exports. |

## Relationships

```text
Learner ── has ──▶ LearningRecord ── for ──▶ Learning Item
   │                    │                         │
   │                    ▼                         │
   └──────── audited by shared rules ─────────────┘
                         │
                         ▼
                  ComplianceGap[]
                         │
                         ▼
                  EvidenceLedger
```

- A **Learner** can have many **Learning Records**.
- A **Learning Item** can appear in many **Learning Records**.
- Each **Learning Record** ties one learner to one learning item and preserves
  source-system evidence such as source IDs, due dates, scores, exemptions, and
  expiry dates.
- The audit engine reads normalized learner, learning item, and record data to
  find **Compliance Gaps**.
- Every audit writes an **Evidence Ledger** entry with hashes of the inputs and
  outputs.

## Example Dialogue

> **Operator:** Canvas calls this an enrollment and Cornerstone calls it a
> transcript item. Are those different things in ComplyOS?
>
> **ComplyOS:** They are different source-system shapes, but they normalize to
> the same `LearningRecord` contract.
>
> **Operator:** So a Canvas enrollment for FERPA and a Cornerstone transcript for
> security training can use one audit model?
>
> **ComplyOS:** Yes. Canvas, Cornerstone, and CSV exports keep their source IDs
> and payload evidence, then map assignment/completion/exemption/due-date/expiry
> data into `LearningRecord`. The existing `Enrollment` model remains available
> as the compatibility layer for the current audit engine.

## Current State (850+ tests passing; 878 at last count, 2026-07-04)

### Built

**Service / authorization layer**
- Every business workflow routes through application services that call `require_permission(context, PERM_*)` — a single authorization choke-point. Services: AuditService, EvidenceService, RemediationService, ImportService, ConnectorRegistry, PolicyRuleService, AIProposalService, PrivacyProgramService, ReadinessService, SecurityEvidenceService, GovernancePacketService, SourceIntelService, NotificationOutboxService, InboundHookService, RoleAdminService, TrendAnalyticsService, AttestationService, IntakeService, RostersService.
- An `ActorContext` (tenant_id, actor_id, role, permissions, surface, request_id) is carried into every service call. Roles map to a 37-permission catalog (`complyos/services/context.py`).
- `LocalRepository` is decomposed into cohesive mixins — PrivacyRepositoryMixin, ImportRepositoryMixin, SourceIntelRepositoryMixin, NotificationRepositoryMixin, RoleBindingRepositoryMixin — behind a typed `RepositoryBase`.

**Surfaces (all call the same services; cross-surface parity enforced by tests)**
- **CLI (Typer):** audit / report / status / digest / dashboard / serve-dashboard / sync / connectors / health / validate-rule / preview-rule / remediate / export / notifications / security evidence / governance packet / privacy / admin role-bindings / source-intel / mcp / run-schedule / release-check.
- **MCP (FastMCP, 38 tools):** same services; default role is least-privilege `agent_service_account` (proposal-only); privileged ops require `COMPLYOS_MCP_ROLE` opt-in.
- **API v1 (FastAPI, `/api/v1/*`):** versioned routes covering audits, learners, connectors, imports (preview/decisions/promote), evidence, exports/reports, rules (validate/preview), remediations, ai/proposals (mapping/approve), readiness, admin/roles, sync, privacy (requests/legal-holds/retention), source-intel, notifications, hooks/inbound. Bearer-token auth (fail-closed when `COMPLYOS_API_TOKEN` unset; constant-time compare). Structured errors `{code,message,details,request_id}`. OpenAPI snapshot test. In-process per-identity rate limiting on mutating endpoints (`COMPLYOS_RATE_LIMIT_PER_MINUTE`).
- **Web shell (`/shell`):** authenticated enterprise web shell served by `complyos serve-dashboard`. Signed-session cookie auth wraps the same `ActorContext` (login exchanges the API token, or a chosen role in `COMPLYOS_ALLOW_INSECURE_LOCAL` mode, for an `HttpOnly SameSite=Lax` signed cookie). Ten modules rendered from live service data: Overview, Gaps, Imports, Records, Evidence, Remediation, Source intelligence, Privacy & retention, Readiness, Administration. Import preview/decide/promote are wired. WCAG 2.2 AA accessibility and color-contrast enforced by tests.

**AI proposal layer**
- Proposal-only: can suggest field mappings, anomaly summaries, gap explanations, remediation-message drafts, and duplicate clustering. Cannot mark a learner compliant, promote imports, execute remediation, or change rules. PII is redacted before any hash/stored output. Proposals have a reject + expiry-TTL lifecycle and full provenance hashes.

**Tenant model**
- Tenant-aware data model, single-tenant runtime by default. Tenant governance metadata (data_region, processing_purpose, data_categories, retention_policy, subprocessor_profile) is surfaced through readiness. Multi-tenant / SaaS is deliberately not built — see `docs/multi-tenancy.md`.

**Connectors:** CSV (read-only), Workday, SAP SuccessFactors, Cornerstone, Canvas (read-only), Moodle (read-only), Blackboard (read-only), D2L Brightspace (read-only), Mock.

**Test suite:** 850+ passing (878 at last count, 2026-07-04); adversarial suite includes BOLA/IDOR, secrets audit, cross-surface denial parity, export formula/XSS neutralization, import adversarial cases, and connector-failure-fails-closed.

---

## Flagged Ambiguities

- **`BSL` is ambiguous.** Use `BUSL-1.1` when referring to Business Source
  License 1.1. `BSL-1.0` usually means the unrelated Boost Software License.
- **`Enrollment` is too narrow for cross-LMS language.** Some systems expose
  transcripts, assignments, submissions, completions, exemptions, or
  recertifications instead of enrollments. Use `LearningRecord` in connector and
  cross-market documentation.
- **`Course` is acceptable in current code.** The implementation still uses
  `Course`, but cross-market docs should prefer **Learning Item** because
  Workforce and Campus systems do not always call the required object a course.
- **Compliance claims must stay scoped.** Use readiness/control mapping,
  evidence-backed, and auditor/counsel review language. Do not say ComplyOS is
  SOC 2/GDPR/FERPA/COPPA certified or equivalent unless a reviewed artifact
  authorizes that exact wording.
- **AI is proposal-only.** AI can propose mappings and drafts; it cannot mark
  people compliant, promote imports, send remediation, or make employment or
  education decisions.
- **Multi-tenant / SaaS is not built.** The runtime is single-tenant. See `docs/multi-tenancy.md` for the deliberate scope boundary.
