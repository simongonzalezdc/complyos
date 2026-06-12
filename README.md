# ComplyOS

[![Source of truth](https://img.shields.io/badge/source-Forgejo-609966.svg)](#source-of-truth)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/badge/license-BUSL--1.1-orange.svg)](LICENSE)

**HR/L&D compliance operations and learning-evidence MCP/API/CLI toolkit**

ComplyOS turns HRIS, LMS, and CSV learning records into tenant-scoped evidence, gap reports, DSR workflows, retention cleanup, and readiness packets for HR, People Ops, L&D, security, and campus teams. It is readiness/control-mapping software, not a certification badge or automated employment-decision system.

---

## Why ComplyOS?

Enterprise compliance tracking still runs on CSV exports, stale dashboards, screenshots, and "I thought they completed that" moments. ComplyOS treats learning compliance as an evidence problem:

- **Evidence-backed audits** — Reports cite tenant-scoped SHA256 evidence entries and action logs.
- **Import governance** — Preview/quarantine/promote CSV rows instead of letting bad exports mutate truth.
- **Privacy workflows** — Create DSR cases, require controller approval, block deletion on legal hold, and dry-run retention cleanup.
- **Security and governance packets** — Collect readiness-only SOC 2-style control evidence and AI/school/FCRA boundary packets for review.
- **Agent-native surfaces** — Use the same service-backed workflows through CLI, API v1, and MCP tools.
- **Local-first** — SQLite by default, PostgreSQL-ready URLs when deployment needs them.

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   MCP Client    │────▶│  ComplyOS MCP    │────▶│ Compliance      │
│ (Claude/Cursor) │     │  Server (FastMCP)│     │ Auditor         │
└─────────────────┘     └──────────────────┘     └────────┬────────┘
                                                          │
                           ┌──────────────────────────────┼──────────────┐
                           │                              │              │
                    ┌──────▼──────┐            ┌──────────▼─────┐  ┌────▼─────┐
                    │ CSV / Mock  │            │   Workday      │  │ SAP/CSOD │
                    │ Connectors  │            │   Connector    │  │Connectors│
                    └─────────────┘            └────────────────┘  └──────────┘
```

---

## Source of truth

Forgejo is the source-of-truth remote for ComplyOS. Do not push ComplyOS changes to GitHub unless the repository owner explicitly asks for a mirror or legacy export.

## Quick Start

### Installation

```bash
# Clone from the Forgejo remote you were granted
git clone <forgejo-complyos-remote>
cd complyos

# Install with uv (recommended)
uv sync --all-extras --dev

# Or with pip
pip install -e ".[dev]"
```

### CLI Usage

```bash
# Initialize profile-specific starter configs
complyos init --profile workforce
complyos init --profile campus --output campus.yaml

# Inspect profile-specific connector capability matrices
complyos connectors --profile workforce
complyos connectors --profile campus --json

# Run a compliance audit
complyos audit

# Filter by department
complyos audit --department Engineering

# Generate a structured report
complyos report --department Engineering --json

# Check a single user's status
complyos status u1

# What changed since the last audit? (new gaps, resolved gaps, trend)
complyos digest

# Generate a self-contained HTML dashboard (summary, trend, filterable table)
complyos dashboard --open

# Serve the live dashboard API locally
complyos serve-dashboard --host 127.0.0.1 --port 8000

# Run configured scheduled audits once from cron/systemd/Forgejo Actions
complyos run-schedule --config complyos.yaml

# Check release-readiness artifacts
complyos release-check --json

# Collect readiness/control packets for review
complyos security evidence --period current --json
complyos governance packet --lane workforce --json

# Operate privacy/DSR and retention workflows through service gates
complyos privacy request <subject-id> --type access --json
complyos privacy approve <request-id> --note "controller approved" --json
complyos privacy export <request-id> --json
complyos privacy retention configure --raw-import-days 30 --evidence-days 2555 --action-log-days 2555 --ai-proposal-days 180 --privacy-request-days 365 --json
complyos privacy retention run --dry-run --json

# Export a self-contained HTML audit report
complyos export --output report.html

# Sync LMS data to local SQLite
complyos sync

# Validate an assignment rule before deploying
complyos validate-rule rule.json

# Preview who would be affected by a rule
complyos preview-rule rule.json

# Check connector health
complyos health

# Send reminders / manager notifications for current gaps
complyos remediate --dry-run
```

### MCP Server

```bash
# Start the MCP server
complyos mcp
```

Then configure your MCP client (Claude Code, Cursor, etc.) to point to the server.

---

## Connectors

| Platform | Status | Auth |
|----------|--------|------|
| CSV export (any LMS/HRIS) | ✅ Supported | None |
| Workday Learning | ✅ Supported | Basic Auth (env vars) |
| SAP SuccessFactors Learning | ✅ Supported | OAuth 2.0 |
| Cornerstone OnDemand Learning | ✅ Supported | OAuth 2.0 |
| Canvas, Moodle, Blackboard, D2L Brightspace | Roadmap / profile targets | Varies |
| Mock (seed data) | ✅ Built-in | None |

### CSV Configuration

No API access needed — point ComplyOS at a directory containing your LMS
export as `users.csv`, `courses.csv`, and `enrollments.csv`:

```bash
export COMPLYOS_CSV_DIR=./examples/csv   # try it with the bundled sample data
complyos audit

# Try profile-specific sample exports
COMPLYOS_CSV_DIR=examples/csv-workforce complyos audit
COMPLYOS_CSV_DIR=examples/csv-campus complyos audit
```

Common column-name variants are recognized automatically (`User ID`,
`Email Address`, `Learner ID`, `Completion Status`, `Deadline`, ...), so
exports from Canvas, Cornerstone, Moodle, Docebo, and similar systems work
without reformatting. The CSV source is read-only: audits and reports work
fully, but reminder remediation requires an API-backed connector.

### Workday Configuration

Set environment variables:

```bash
export WORKDAY_BASE_URL="https://your-workday-instance.com"
export WORKDAY_USERNAME="your-user"
export WORKDAY_PASSWORD="your-pass"
```

---

## Development

```bash
# Run tests
uv run pytest -q

# Run with coverage
uv run pytest --cov=complyos --cov-report=term-missing

# Lint
uv run ruff check complyos tests

# Type check
uv run mypy complyos --ignore-missing-imports
```

---

## Domain Model

ComplyOS normalizes Workforce and Campus source data into one shared audit
model. The cross-LMS connector contract normalizes transcripts, enrollments,
assignments, submissions, completions, exemptions, and recertifications into
`LearningRecord`. The existing `Enrollment` model remains for compatibility with
the current audit engine.

```python
LearningRecord(
    id="lr1",
    user_id="u1",
    course_id="c1",
    source_system="cornerstone",
    source_record_id="csod-transcript-1",
    status="completed",
    expires_at="2026-01-20",
)

ComplianceGap(
    user=User(id="u1", department="Engineering", ...),
    missing_courses=[Course(code="SEC-101", mandatory=True)],
    severity="high",  # critical | high | medium | low
    days_overdue=14,
    rule_name="Mandatory Compliance Training",
)
```

Every audit produces a tenant-scoped `EvidenceLedgerEntry` with SHA256 hashes for auditor/counsel review. Action logs record who did what without turning readiness software into a legal-status claim.

---

## Roadmap

- [x] Phase 1 — Core auditor, MCP server, CLI, Workday connector, tests
- [x] Phase 2 — SQLite persistence, assignment rules engine, sync command
- [x] Phase 3 — Remediation workflows, CSV connector, compliance digest, HTML dashboard
- [x] Phase 4 — Operator-ready release: scheduled audit runs, Slack/Teams notifications, release packaging, and documentation/security polish
- [x] Phase 5 — Scale-out: PostgreSQL backend, live web dashboard, SAP SuccessFactors connector, Cornerstone connector
- [x] Enterprise readiness foundation — tenant-scoped evidence, API/MCP/CLI parity for privacy workflows, retention cleanup, security evidence packet, and governance packet

Remaining work is mostly outside application code: counsel-approved terms, customer-specific retention schedules, production security receipts, backup/restore evidence, access-review evidence, accessibility audit/VPAT where needed, and auditor review.

---

## License

ComplyOS uses **Business Source License 1.1**, SPDX identifier `BUSL-1.1`.
Avoid the shorthand "BSL" here: `BSL-1.0` usually means the unrelated Boost
Software License.

This is a source-available license. The source code is visible and may be
copied, modified, redistributed, and used for non-production purposes.
Production use requires a commercial license unless a future Additional Use
Grant says otherwise.

On 2030-06-11, or the fourth anniversary of the first public distribution of
a specific version under this license, whichever comes first, that version
converts to **Apache License 2.0**.
