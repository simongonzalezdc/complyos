# ComplyOS Architecture

## Overview

ComplyOS is a layered HR/L&D and campus learning-evidence system. It bridges LMS/HRIS records, CSV exports, API automation, MCP agents, and readiness-control packets without turning the product into an automated employment-decision system. It follows a **local-first** philosophy: data is cached in SQLite by default, with PostgreSQL-ready URLs for deployments that need them.

```
┌───────────────────────────────────────────────────────────────────────┐
│                          Interface Layer                              │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐  ┌───────────────┐  │
│  │   CLI    │  │  MCP     │  │   FastAPI       │  │  Web Shell    │  │
│  │ (Typer)  │  │(FastMCP) │  │   API v1        │  │ /shell (auth) │  │
│  └────┬─────┘  └────┬─────┘  └────────┬────────┘  └───────┬───────┘  │
└───────┼─────────────┼─────────────────┼───────────────────┼──────────┘
        │             │                 │                   │
        └─────────────┴─────────────────┴───────────────────┘
                                │
                    (ActorContext + require_permission)
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│                       Application Service Layer                       │
│  AuditService · EvidenceService · RemediationService · ImportService  │
│  ConnectorRegistry · PolicyRuleService · AIProposalService            │
│  PrivacyProgramService · ReadinessService · SecurityEvidenceService   │
│  GovernancePacketService · SourceIntelService                         │
│  NotificationOutboxService · InboundHookService · RoleAdminService    │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│                          Data Layer                                   │
│  LocalRepository (composed from mixins behind RepositoryBase)         │
│  PrivacyRepositoryMixin · ImportRepositoryMixin                       │
│  SourceIntelRepositoryMixin · NotificationRepositoryMixin             │
│  RoleBindingRepositoryMixin · RepositoryMappers                       │
│  ──────────────────────────────────────────────────────               │
│  Domain Models (Pydantic v2) · SQLite (default) / PostgreSQL          │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│                         Connector Layer                               │
│  CSV (read-only) · Mock · Workday · SAP SuccessFactors · Cornerstone  │
└───────────────────────────────────────────────────────────────────────┘
```

## Authorization Model

Every business workflow routes through the **application service layer**. Services call `require_permission(context, PERM_*)` as the single authorization choke-point — no surface (CLI, MCP, API, shell) can bypass it.

### ActorContext

`ActorContext` (defined in `complyos/services/context.py`) carries:

| Field | Purpose |
|-------|---------|
| `tenant_id` | Data isolation boundary |
| `actor_id` | Identity of the calling actor |
| `role` | Named role selecting a permission set |
| `permissions` | Tuple of granted `PERM_*` strings |
| `surface` | `"cli"` / `"mcp"` / `"api"` / `"shell"` |
| `request_id` | Per-request correlation UUID |
| `auth_method` | `"bearer"` / `"session"` / `"local_dev"` |

### Permission Catalog (35 permissions)

```
audit:read              audit:run              analytics:read
evidence:read           evidence:export
import:preview          import:decide          import:promote
rules:read              rules:preview          rules:write
remediation:propose     remediation:execute
connectors:read         connectors:write
ai:propose              ai:approve
readiness:read
security:evidence:read
governance:read
privacy:request         privacy:approve        privacy:export
privacy:delete          privacy:retention:manage
legal_hold:manage
source_intel:read       source_intel:run       source_intel:decide
notifications:manage
attestation:record      attestation:read
intake:submit           intake:confirm
admin:manage
```

### Role-to-Permission Mapping

| Role | Permissions |
|------|------------|
| `owner` | All 35 |
| `admin` | All except `admin:manage` |
| `compliance_manager` | Audit, analytics:read, evidence, rules, remediation, connectors:read, AI, readiness, security/governance read, privacy (request/approve/export), source-intel, notifications, attestation, intake (submit + confirm) |
| `privacy_admin` | Evidence:read, readiness:read, privacy (all), legal hold, notifications |
| `import_approver` | import:preview/decide/promote, evidence:read |
| `importer` | import:preview/decide, evidence:read |
| `reviewer` | audit:read, analytics:read, evidence, readiness, security/governance read, source-intel:read |
| `agent_service_account` | audit:read/run, analytics:read, evidence:read, import:preview, rules:preview, remediation:propose, connectors:read, ai:propose, readiness:read, source-intel:read/run, attestation:read, intake:submit (**no** notifications:manage, attestation:record, or intake:confirm — MCP default role is proposal-only and cannot confirm scope) |
| `read_only` | audit:read, analytics:read, evidence:read, readiness:read, source-intel:read |

## Application Services

All surfaces instantiate services with a repository and call them with an `ActorContext`. Services own enforcement; surfaces cannot mutate compliance state without passing through a service.

| Service | Responsibility |
|---------|---------------|
| `AuditService` | Run audits, generate reports, compute gaps |
| `TrendAnalyticsService` | Period-bucketed trend metrics and the BI-ready learner x requirement feed |
| `EvidenceService` | Evidence ledger, render reports |
| `RemediationService` | Propose and execute remediation actions |
| `ImportService` | Preview / quarantine / decide / promote import batches |
| `ConnectorRegistry` | Resolve and health-check LMS connectors |
| `PolicyRuleService` | Validate and preview assignment rules |
| `AIProposalService` | Proposal-only AI operations (mapping, anomaly, gap, remediation draft, clustering) |
| `PrivacyProgramService` | DSR workflows, legal holds, retention cleanup |
| `ReadinessService` | Tenant readiness metadata and control-mapping evidence |
| `SecurityEvidenceService` | Security evidence packets |
| `GovernancePacketService` | Governance review packets |
| `SourceIntelService` | Source-intelligence proposals and decisions |
| `NotificationOutboxService` | Enqueue and drain outbound notifications |
| `InboundHookService` | Validate, redact, and record inbound webhook receipts |
| `RoleAdminService` | Manage role bindings per tenant |

## Surfaces

All four surfaces call **the same services** with an `ActorContext`. No mutating capability is MCP-only or shell-only. Cross-surface denial parity is enforced by adversarial tests.

### CLI (Typer)

Commands: `audit`, `report`, `status`, `digest`, `dashboard`, `serve-dashboard`, `sync`, `connectors`, `health`, `validate-rule`, `preview-rule`, `remediate`, `export`, `notifications`, `security evidence`, `governance packet`, `privacy …`, `admin role-bindings`, `source-intel …`, `mcp`, `run-schedule`, `release-check`.

File-writing HTML/dashboard exports are CLI- and MCP-only by design (they write to local paths; the API surface returns rendered content in the response body instead).

### MCP (FastMCP)

Approximately 30 tools over the same services. The default role is `agent_service_account` — proposal-only with no write-back capability. Privileged operations require opting in via `COMPLYOS_MCP_ROLE`.

### API v1 (FastAPI, prefix `/api/v1`)

Versioned routes covering: `audits`, `report`, `learners/{id}/status`, `digest`, `connectors`, `imports` (preview/decisions/promote), `evidence`, `exports/reports`, `rules` (validate/preview), `remediations`, `ai/proposals` (mapping/approve), `readiness`, `admin/roles`, `sync`, `privacy` (requests/legal-holds/retention), `source-intel`, `notifications`, `hooks/inbound`.

**Auth**: Bearer-token auth via `Authorization: Bearer <token>`. Fail-closed when `COMPLYOS_API_TOKEN` is unset — the API rejects requests rather than silently allowing attacker-controlled role headers. Constant-time HMAC comparison avoids timing side channels. Explicit `COMPLYOS_ALLOW_INSECURE_LOCAL=1` enables header-driven role trust for local-only use.

**Errors**: Structured `{code, message, details, request_id}` on every error path.

**Rate limiting**: In-process per-identity rate limiting on mutating endpoints. Configurable via `COMPLYOS_RATE_LIMIT_PER_MINUTE`. Exceeded requests receive 429 + `Retry-After`.

**OpenAPI**: Snapshot test guards the schema from silent drift.

### Web Shell (FastAPI, prefix `/shell`)

An authenticated enterprise web shell served by `complyos serve-dashboard` at `http://host:port/shell`. Not a mock or marketing page — every module reads live service data.

**Auth**: Signed-session cookie (`complyos_shell`). Login exchanges a valid API token (or a role choice under `COMPLYOS_ALLOW_INSECURE_LOCAL`) for an `HttpOnly SameSite=Lax` cookie signed with HMAC-SHA256 (`COMPLYOS_SESSION_SECRET`, or falls back to `COMPLYOS_API_TOKEN`). The cookie carries an opaque signed role token; `shell_context` verifies the signature and rebuilds the same `ActorContext` that all services consume. Clients never receive a forgeable plaintext role.

**Modules** (all live, rendering from service data):

| # | Module | Service data source |
|---|--------|---------------------|
| 1 | Overview | AuditService |
| 2 | Gaps | AuditService |
| 3 | Imports | ImportService |
| 4 | Evidence | EvidenceService |
| 5 | Remediation | RemediationService |
| 6 | Source intelligence | SourceIntelService |
| 7 | Privacy & retention | PrivacyProgramService |
| 8 | Readiness | ReadinessService |
| 9 | Administration | RoleAdminService |

Import preview/decide/promote are wired in the shell. WCAG 2.2 AA accessibility and color-contrast are enforced by tests.

## AI Proposal Layer

`AIProposalService` is **proposal-only**. It can suggest mappings, anomaly summaries, gap explanations, remediation-message drafts, and duplicate clusters. It cannot:

- Mark a learner as compliant
- Promote an import batch
- Execute remediation
- Change or write rules

PII is redacted before any data enters a hash or stored output. Prompt-injection is inert because the proposal pipeline is deterministic. Proposals carry reject + expiry-TTL lifecycle management and full provenance hashes. Human approval is required before any AI proposal affects compliance state.

Deterministic proposal types: field mapping, anomaly summary, gap explanation, remediation-message draft, duplicate clustering.

## Repository Layer

`LocalRepository` (`complyos/core/repository.py`) is composed from cohesive aggregate mixins behind a typed `RepositoryBase`:

| Mixin | Aggregate |
|-------|----------|
| `RepositoryBase` | Session factory, shared helpers, `HoldDecision` evaluation |
| `RepositoryMappers` | ORM-to-domain and domain-to-ORM mapping |
| `PrivacyRepositoryMixin` | DSR/privacy workflow cases, legal holds, retention policies |
| `ImportRepositoryMixin` | Import batches, rows, AI proposals |
| `SourceIntelRepositoryMixin` | Source-intelligence proposals and review packets |
| `NotificationRepositoryMixin` | Notification events, deliveries, preferences, outbox |
| `RoleBindingRepositoryMixin` | Per-tenant actor role bindings |
| Core (in `LocalRepository` body) | Users, courses, enrollments, learning records, audit snapshots, evidence ledger, action log |

Callers still use `repository.<method>` unchanged. The mixin decomposition enforces aggregate boundaries without fragmenting the calling API.

## Domain Model

The core domain is intentionally small and focused:

- **User** — An employee with department, region, manager, and employment status
- **Course** — A training course with mandatory flag and category
- **LearningRecord** — The cross-LMS connector contract: normalized source record for assignment, completion, exemption, score, due date, and expiry data
- **Enrollment** — A user's relationship to a course (status, due date, completion %); retained as the current audit-engine compatibility path
- **ComplianceGap** — A user missing a required course, with severity and overdue days
- **AssignmentRule** — A rule that targets users and assigns courses with deadlines
- **RemediationAction** — An action taken to close a gap (reminder, enroll, notify)
- **EvidenceLedgerEntry** — A tenant-scoped audit trail with SHA256 hashes
- **ActionLogEntry** — Actor/action/object/result log for service-backed operations
- **PrivacyRequest** — Tenant-scoped DSR/privacy workflow case requiring controller approval before export/delete
- **LegalHold** — Subject or tenant-level hold that blocks deletion and retention cleanup
- **RetentionPolicy** — Tenant retention metadata for raw imports, evidence, action logs, AI proposals, and closed privacy cases
- **GovernancePacket / SecurityEvidencePacket** — Readiness-only review packets, not certification artifacts

All domain models are **Pydantic v2** for type safety across API boundaries.

## Data Flow

### Audit Flow

```
Connector.get_users() ──▶ AuditService ──▶ ComplianceGap[]
Connector.get_courses() ──▶      │
Connector.get_enrollments() ──▶  │
                                 ▼
                          EvidenceLedgerEntry
                                 ▼
                           AuditReport
```

The auditor builds an enrollment map (`dict[(user_id, course_id), Enrollment]`) for O(1) gap detection. Connectors expose richer source data as `LearningRecord`; `Enrollment` remains the audit compatibility path. This scales linearly with users × courses.

### Sync Flow

```
Connector ──▶ get_users/get_courses/get_enrollments/get_learning_records ──▶ LocalRepository
                                                                          │
                                                                          ▼
                                                                      SQLite
```

The `sync` command (CLI/API) pulls users, courses, enrollments, and learning records from the connector and replaces the local cache. This enables fast offline queries and powers the assignment rules engine.

### Import Flow (Preview → Decide → Promote)

```
CSV/API/MCP input ──▶ ImportService.preview() ──▶ quarantine + AI mapping proposals
                                │
                                ▼
                     ImportService.decide() ──▶ human accept/reject per row
                                │
                                ▼
                     ImportService.promote() ──▶ evidence ledger + action log
```

Import preview/decide/promote are exposed across all four surfaces (CLI, MCP, API v1, web shell). A promote cannot happen without a human decision record.

### Enterprise Control Flow

```
CSV/API/MCP/shell input ──▶ preview/quarantine ──▶ human decision ──▶ promote
                                      │                               │
                                      ▼                               ▼
                               action log                      evidence ledger
                                      │                               │
                                      └────▶ privacy / retention / governance services
```

Privacy workflows are service-backed on every surface: create request, record controller approval, export/delete subject data, enforce legal holds, configure retention, and dry-run/apply cleanup for eligible closed cases, terminal import payloads, rejected/expired AI proposals, evidence entries, and action logs.

### Rules Flow

```
AssignmentRule ──▶ PolicyRuleService.preview() ──▶ affected users + missing courses
       │
       ▼
PolicyRuleService.validate() ──▶ issues list + preview
```

Rules are validated before deployment to catch unknown courses, empty targets, and zero-match criteria.

## Connector Architecture

Connectors implement `LMSConnector` (ABC) with async methods:

- `authenticate()` — Health check with boolean result
- `get_users(filters)` — Normalize LMS user fields to `User`
- `get_courses(filters)` — Normalize LMS course fields to `Course`
- `get_enrollments(filters)` — Normalize LMS enrollment fields to `Enrollment` for current audit compatibility
- `get_learning_records(filters)` — Normalize LMS transcripts, enrollments, assignments, submissions, completions, exemptions, scores, due dates, and expiry data to `LearningRecord`
- `trigger_reminder(user_id, course_id)` — Send notification

**Workday Connector** uses `httpx.AsyncClient` with basic auth. Data normalization handles Workday's nested JSON structure (e.g., `supervisoryOrganization.descriptor` → `department`).

**CSV Connector** reads `users.csv`, `courses.csv`, and `enrollments.csv` exports from a local directory and normalizes common LMS column names. It is read-only, so audits, reports, digests, and dashboards work without LMS API access, while reminder remediation still requires an API-backed connector.

**SuccessFactors Connector** uses OAuth 2.0 bearer tokens and normalizes SAP SuccessFactors Learning OData user, item, and learning-history payloads into the shared ComplyOS domain model.

**Cornerstone Connector** uses OAuth 2.0 client credentials and normalizes Cornerstone Learning users, learning objects, and transcript records into the shared ComplyOS domain model.

**Mock Connector** provides deterministic seed data for testing without external dependencies.

## Tenant Model

ComplyOS is **tenant-aware** but runs **single-tenant by default**. Every data operation is scoped to a `tenant_id`. Tenant governance metadata (data region, processing purpose, data categories, retention policy, subprocessor profile) is surfaced through `ReadinessService`. Multi-tenant SaaS mode is not built — see `docs/multi-tenancy.md`.

## Evidence and Action Logs

Every audit produces a tenant-scoped `EvidenceLedgerEntry` with:

- `raw_data_hash` — SHA256 of the raw connector response or imported source payload
- `output_hash` — SHA256 of the processed report
- `transformation_steps` — ordered operations applied
- Tenant/source metadata so exported evidence does not bleed across customers

Mutating workflows also write action logs. The combination gives auditors, buyers, and counsel a review trail without claiming legal or certification status.

## Operations and Scalability Notes

The operator-ready path keeps ComplyOS local-first: SQLite remains the default store, scheduled audit runs invoke the same CLI/API/MCP audit paths, and Source Intelligence schedules record DB job executions, action logs, review decisions, and export packets before any downstream rule/module work.

**Notifications** use an outbox pattern. Jobs enqueue tenant-scoped `notification_events` and `notification_deliveries`; a separate `complyos notifications drain` worker sends configured email, Slack, Teams, or generic customer webhooks. `notification_preferences` provides channel/event kill switches before deliveries are created. Outbound hook payloads include event IDs, idempotency keys, payload hashes, and optional HMAC signatures, while delivery rows keep retry, skip, sent, and dead-letter evidence without storing webhook URLs in packets.

**Inbound hooks** are provider-neutral receipts first. `POST /api/v1/hooks/inbound/{source}` validates the API token, optionally verifies `COMPLYOS_INBOUND_WEBHOOK_SECRET`, redacts sensitive fields, stores the payload hash in `inbound_webhook_events`, and records an action log. Canvas, Workday, SuccessFactors, Cornerstone, or customer-specific parsers can sit on top later without changing the receipt/audit foundation.

PostgreSQL-ready SQLAlchemy URLs are available for scale-out deployments without rewriting the auditor. SQLite remains the default local store.

The current SQLite-backed architecture handles ~10K users comfortably. For larger deployments:

1. Add connector pagination beyond the first normalized response page
2. Add provider-specific parsers on top of the generic inbound hook receipt API
3. Cache enrollment maps in Redis for sub-second audits
4. Run audits as background jobs with Celery/ARQ

The domain models and auditor logic are intentionally storage-agnostic — only `repository.py` and `database.py` need to change.

## Testing Strategy

| Layer | Strategy |
|-------|----------|
| Domain models | Pydantic validation tests |
| Connectors | `respx` for HTTP mocking plus CSV fixture tests |
| Auditor | Unit tests with MockConnector |
| Repository | SQLite in-memory (`tmp_path`) |
| Rules engine | Unit tests with seeded repository |
| Remediation | Unit tests with MockConnector |
| Report exporter | File-based assertions |
| Dashboard / web shell | HTML output assertions + WCAG accessibility + color-contrast |
| MCP server | Direct tool invocation |
| CLI | `CliRunner` with stdout capture |
| API v1 | `httpx.AsyncClient` + OpenAPI snapshot |
| Adversarial | BOLA/IDOR, secrets audit, cross-surface denial parity, export formula/XSS neutralization, import adversarial cases, connector-failure-fails-closed |

659 tests pass on this branch. Use the full local test suite as the release baseline when changing connector, repository, or audit behavior; avoid relying on a stale hard-coded test count.

## Claim Discipline

Control-mapping and readiness language only. Never write "SOC 2 compliant", "SOC 2 certified", "GDPR compliant", "FERPA compliant", "COPPA compliant", "LGPD compliant", or "PIPEDA compliant". Use "readiness", "control mapping", "evidence", and "review". A test enforces this at the codebase level.

## Completed Phases

- [x] Phase 1 — Core auditing, MCP server, CLI, Workday connector
- [x] Phase 2 — SQLite cache, assignment rules engine, sync command
- [x] Phase 3 — Remediation workflows, CSV connector, compliance digest, HTML report/dashboard export
- [x] Phase 4 — Operator-ready release: scheduled audit runs, notification outbox, release packaging, and documentation/security polish
- [x] Phase 5 — Scale-out: PostgreSQL backend, live web dashboard, SAP SuccessFactors connector, Cornerstone connector
- [x] Enterprise hardening — Application service layer with `ActorContext` + `require_permission` authorization choke-point; four parity surfaces (CLI/MCP/API v1/web shell); authenticated enterprise web shell with 9 live modules; proposal-only AI layer with PII redaction and provenance; privacy/DSR/legal-hold/retention services; repository mixin decomposition; source-intel and notification outbox; adversarial test suite (659 tests green, ruff+mypy clean)

## Roadmap

Remaining work is mostly outside application code or gated behind explicit product decisions:

- **Multi-tenant hardening** — token→tenant binding, repository-layer tenant scoping (defense in depth), and MCP tenant selection, required before any shared-deployment SaaS posture. Deliberately deferred; see [`docs/multi-tenancy.md`](docs/multi-tenancy.md).
- **Real connector integrations** — Canvas, Moodle, Blackboard, and D2L Brightspace are roadmap targets (capability metadata only today), plus provider-specific inbound-hook parsers on the generic receipt API.
- **Paid regulatory API integration** for Source Intelligence (kept list-only until procured).
- **Production operator evidence** — real SMTP/webhook credentials, security receipts, backup/restore evidence, access-review evidence, accessibility audit / VPAT where needed, counsel-approved terms, and auditor review.
