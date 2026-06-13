# ComplyOS Architecture

## Overview

ComplyOS is a layered HR/L&D and campus learning-evidence system. It bridges LMS/HRIS records, CSV exports, API automation, MCP agents, and readiness-control packets without turning the product into an automated employment-decision system. It follows a **local-first** philosophy: data is cached in SQLite by default, with PostgreSQL-ready URLs for deployments that need them.

```
┌─────────────────────────────────────────────────────────────┐
│                      Interface Layer                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   CLI       │  │  MCP Server │  │   FastAPI / Python  │  │
│  │  (Typer)    │  │  (FastMCP)  │  │   API v1 + async    │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
┌─────────┼────────────────┼────────────────────┼─────────────┐
│         │   Application Layer                 │             │
│  ┌──────┴──────┐  ┌─────────────┐  ┌─────────┴──────────┐  │
│  │  Compliance │  │ Privacy /   │  │ Security +         │  │
│  │  Auditor    │  │ Import Gates│  │ Governance Packets │  │
│  └──────┬──────┘  └──────┬──────┘  └─────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
┌─────────┼────────────────┼────────────────────┼─────────────┐
│         │   Data Layer                        │             │
│  ┌──────┴──────┐  ┌─────────────┐  ┌─────────┴──────────┐  │
│  │  Repository │  │   Domain    │  │   Evidence         │  │
│  │  (SQLite)   │  │   Models    │  │   Ledger           │  │
│  └──────┬──────┘  └─────────────┘  └────────────────────┘  │
└─────────┼───────────────────────────────────────────────────┘
          │
┌─────────┼───────────────────────────────────────────────────┐
│         │   Connector Layer                                   │
│  ┌──────┴──────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ CSV / Mock  │  │   Workday   │  │ SAP SuccessFactors │  │
│  │ Connectors  │  │  Connector  │  │ + Cornerstone      │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Domain Model

The core domain is intentionally small and focused:

- **User** — An employee with department, region, manager, and employment status
- **Course** — A training course with mandatory flag and category
- **LearningRecord** — The cross-LMS connector contract: a normalized source record for assignment, completion, exemption, score, due date, and expiry data
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
Connector.get_users() ──▶ Auditor ──▶ ComplianceGap[]
Connector.get_courses() ──▶    │
Connector.get_enrollments() ──▶│
                               ▼
                        EvidenceLedgerEntry
                               ▼
                         AuditReport
```

The auditor currently builds an enrollment map (`dict[(user_id, course_id), Enrollment]`) for O(1) gap detection. Connectors should expose richer source data as `LearningRecord`, then keep `Enrollment` available as the compatibility path for the current auditor and reports. This scales linearly with users × courses rather than requiring nested loops over enrollments.

### Sync Flow

```
Connector ──▶ get_users/get_courses/get_enrollments/get_learning_records ──▶ LocalRepository
                                                                         │
                                                                         ▼
                                                                     SQLite
```

The `sync` CLI command pulls users, courses, enrollments, and learning records from the connector and replaces the local cache. `LearningRecord` is the cross-LMS connector contract; `Enrollment` remains the audit compatibility path while the current auditor consumes enrollment-shaped status data. This enables fast offline queries and powers the assignment rules engine.

### Rules Flow

```
AssignmentRule ──▶ RuleEngine.preview() ──▶ affected users + missing courses
        │
        ▼
RuleEngine.validate() ──▶ issues list + preview
```

Rules are validated before deployment to catch unknown courses, empty targets, and zero-match criteria.

### Enterprise Control Flow

```
CSV/API/MCP input ──▶ preview/quarantine ──▶ human decision ──▶ promote
                                │                              │
                                ▼                              ▼
                         action log                    evidence ledger
                                │                              │
                                └────▶ privacy / retention / governance services
```

Privacy workflows are service-backed on every surface: create request, record controller approval, export/delete subject data, enforce legal holds, configure retention, and dry-run/apply cleanup for eligible closed cases, terminal import payloads, rejected/expired AI proposals, evidence entries, and action logs.

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

## Testing Strategy

| Layer | Strategy | Coverage |
|-------|----------|----------|
| Domain models | Pydantic validation tests | 100% |
| Connectors | `respx` for HTTP mocking plus CSV fixture tests | 88–98% |
| Auditor | Unit tests with MockConnector | 98% |
| Repository | SQLite in-memory (`tmp_path`) | 97% |
| Rules engine | Unit tests with seeded repository | 99% |
| Remediation | Unit tests with MockConnector | 95% |
| Report exporter | File-based assertions | 100% |
| Dashboard | File-based assertions for generated HTML | 100% |
| MCP server | Direct tool invocation | 85% |
| CLI | `CliRunner` with stdout capture | 76% |

Use the full local test suite as the release baseline when changing connector, repository, or audit behavior; avoid relying on a stale hard-coded test count.

## Evidence and action logs

Every audit produces a tenant-scoped `EvidenceLedgerEntry` with:

- `raw_data_hash` — SHA256 of the raw connector response or imported source payload
- `output_hash` — SHA256 of the processed report
- `transformation_steps` — ordered operations applied
- tenant/source metadata so exported evidence does not bleed across customers

Mutating workflows also write action logs. The combination gives auditors, buyers, and counsel a review trail without pretending the product has achieved legal or certification status.

## Operations and Scalability Notes

The operator-ready path keeps ComplyOS local-first: SQLite remains the default
store, scheduled audit runs invoke the same CLI/API/MCP audit paths, and Source
Intelligence schedules record DB job executions, action logs, review decisions,
and export packets before any downstream rule/module work. Email, Slack, Teams,
and generic webhook notifications consume audit output through the shared outbox
rather than introducing a separate workflow engine.

Notifications use an outbox pattern. Jobs enqueue tenant-scoped
`notification_events` and `notification_deliveries`; a separate
`complyos notifications drain` worker sends configured email, Slack, Teams, or
generic customer webhooks. `notification_preferences` provides channel/event
kill switches before deliveries are created. Outbound hook payloads include
event IDs, idempotency keys, payload hashes, and optional HMAC signatures, while
delivery rows keep retry, skip, sent, and dead-letter evidence without storing
webhook URLs in packets.

Inbound hooks are provider-neutral receipts first, not LMS-specific automation.
`POST /api/v1/hooks/inbound/{source}` validates the API token, optionally
verifies `COMPLYOS_INBOUND_WEBHOOK_SECRET`, redacts sensitive fields, stores the
payload hash in `inbound_webhook_events`, and records an action log. Canvas,
Workday, SuccessFactors, Cornerstone, or customer-specific parsers can sit on top
later without changing the receipt/audit foundation.

PostgreSQL-ready SQLAlchemy URLs and a live FastAPI dashboard are available for scale-out deployments without rewriting the auditor. SQLite remains the default local store.

The current SQLite-backed architecture handles ~10K users comfortably. For larger deployments:

1. Add connector pagination beyond the first normalized response page
2. Add provider-specific parsers on top of the generic inbound hook receipt API
3. Cache enrollment maps in Redis for sub-second audits
4. Run audits as background jobs with Celery/ARQ

The domain models and auditor logic are intentionally storage-agnostic — only `repository.py` and `database.py` need to change.

## Roadmap

- [x] Phase 1 — Core auditing, MCP server, CLI, Workday connector
- [x] Phase 2 — SQLite cache, assignment rules engine, sync command
- [x] Phase 3 — Remediation workflows, CSV connector, compliance digest, HTML report/dashboard export
- [x] Phase 4 — Operator-ready release: scheduled audit runs, notification outbox, release packaging, and documentation/security polish
- [x] Phase 5 — Scale-out: PostgreSQL backend, live web dashboard, SAP SuccessFactors connector, Cornerstone connector
- [x] Enterprise readiness layer — privacy/DSR services, retention cleanup, tenant-scoped evidence, security evidence packet, governance packet, with CLI/MCP/API parity. The FastAPI surface exposes the enterprise/privacy workflows AND the core audit operations (`/audit`, `/report`, `/users/{id}/status`, `/digest`, `/connectors/health`, `/remediate`), each gated by the same `require_permission` checks. The file-writing HTML/dashboard exports remain CLI- and MCP-only by design (they write to local paths).
