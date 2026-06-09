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
│  │   Mock      │  │   Workday   │  │   SAP / CSOD        │  │
│  │ Connector   │  │  Connector  │  │   (planned)         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

## Domain Model

The core domain is intentionally small and focused:

- **User** — An employee with department, region, manager, and employment status
- **Course** — A training course with mandatory flag and category
- **Enrollment** — A user's relationship to a course (status, due date, completion %)
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

The auditor builds an enrollment map (`dict[(user_id, course_id), Enrollment]`) for O(1) gap detection. This scales linearly with users × courses rather than requiring nested loops over enrollments.

### Sync Flow

```
Connector ──▶ get_users/get_courses/get_enrollments ──▶ LocalRepository
                                                            │
                                                            ▼
                                                        SQLite
```

The `sync` CLI command pulls all data from the connector and replaces the local cache. This enables fast offline queries and powers the assignment rules engine.

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
- `get_enrollments(filters)` — Normalize LMS enrollment fields to `Enrollment`
- `trigger_reminder(user_id, course_id)` — Send notification

**Workday Connector** uses `httpx.AsyncClient` with basic auth. Data normalization handles Workday's nested JSON structure (e.g., `supervisoryOrganization.descriptor` → `department`).

**Mock Connector** provides deterministic seed data for testing without external dependencies.

## Testing Strategy

| Layer | Strategy | Coverage |
|-------|----------|----------|
| Domain models | Property-based validation | 100% |
| Connectors | `respx` for HTTP mocking | 96% |
| Auditor | Unit tests with MockConnector | 98% |
| Repository | SQLite in-memory (`tmp_path`) | 96% |
| Rules engine | Unit tests with seeded repository | 99% |
| Remediation | Unit tests with MockConnector | 92% |
| Report exporter | File-based assertions | 100% |
| MCP server | Direct tool invocation | 96% |
| CLI | `CliRunner` with stdout capture | 93% |

**Total: 119 tests, 96% line coverage**

## Evidence Ledger

Every audit produces an `EvidenceLedgerEntry` with:

- `raw_data_hash` — SHA256 of the raw connector response
- `output_hash` — SHA256 of the processed report
- `transformation_steps` — Ordered list of operations applied

This satisfies regulator requirements for audit trails without requiring blockchain or external services.

## Scalability Notes

The current SQLite-backed architecture handles ~10K users comfortably. For larger deployments:

1. Replace `LocalRepository` with a PostgreSQL-backed implementation
2. Add pagination to connector methods
3. Cache enrollment maps in Redis for sub-second audits
4. Run audits as background jobs with Celery/ARQ

The domain models and auditor logic are intentionally storage-agnostic — only `repository.py` and `database.py` need to change.

## Roadmap

- [x] Phase 1 — Core auditing, MCP server, CLI, Workday connector
- [x] Phase 2 — SQLite cache, assignment rules engine, sync command
- [x] Phase 3 — Remediation workflows, HTML report export
- [ ] Phase 4 — PostgreSQL backend, web dashboard, Slack notifications
