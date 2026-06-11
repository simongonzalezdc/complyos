# ComplyOS Architecture

## Overview

ComplyOS is a layered compliance auditing system that bridges enterprise LMS platforms with AI-native interfaces. It follows a **local-first** philosophy: all data is cached in SQLite by default, with optional real-time connector fallbacks.

```
┌─────────────────────────────────────────────────────────────┐
│                      Interface Layer                        │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   CLI       │  │  MCP Server │  │   Python API        │  │
│  │  (Typer)    │  │  (FastMCP)  │  │   (async/await)     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼────────────────────┼─────────────┘
          │                │                    │
┌─────────┼────────────────┼────────────────────┼─────────────┐
│         │   Application Layer                 │             │
│  ┌──────┴──────┐  ┌─────────────┐  ┌─────────┴──────────┐  │
│  │  Compliance │  │ Assignment  │  │   Remediation      │  │
│  │  Auditor    │  │ Rule Engine │  │   Engine           │  │
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
│  │ CSV / Mock  │  │   Workday   │  │   SAP / CSOD        │  │
│  │ Connectors  │  │  Connector  │  │   (future)          │  │
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
- **EvidenceLedgerEntry** — An immutable audit trail with SHA256 hashes

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

## Evidence Ledger

Every audit produces an `EvidenceLedgerEntry` with:

- `raw_data_hash` — SHA256 of the raw connector response
- `output_hash` — SHA256 of the processed report
- `transformation_steps` — Ordered list of operations applied

This satisfies regulator requirements for audit trails without requiring blockchain or external services.

## Operations and Scalability Notes

The operator-ready path keeps ComplyOS local-first: SQLite remains the default store, scheduled runs invoke the same CLI/MCP audit paths, and Slack/Teams notifications consume remediation output rather than introducing a separate workflow engine.

PostgreSQL and a live web dashboard are scale-out work, not prerequisites for the first operator-ready release. The repository and domain model boundaries are already shaped so that storage and UI can change later without rewriting the auditor.

The current SQLite-backed architecture handles ~10K users comfortably. For larger deployments:

1. Replace `LocalRepository` with a PostgreSQL-backed implementation
2. Add pagination to connector methods
3. Cache enrollment maps in Redis for sub-second audits
4. Run audits as background jobs with Celery/ARQ

The domain models and auditor logic are intentionally storage-agnostic — only `repository.py` and `database.py` need to change.

## Roadmap

- [x] Phase 1 — Core auditing, MCP server, CLI, Workday connector
- [x] Phase 2 — SQLite cache, assignment rules engine, sync command
- [x] Phase 3 — Remediation workflows, CSV connector, compliance digest, HTML report/dashboard export
- [ ] Phase 4 — Operator-ready release: scheduled audit runs, Slack/Teams notifications, release packaging, and documentation/security polish
- [ ] Phase 5 — Scale-out: PostgreSQL backend, live web dashboard, SAP SuccessFactors connector, Cornerstone connector
