# ComplyOS

[![CI](https://github.com/simongonzalezdc/complyos/actions/workflows/ci.yml/badge.svg)](https://github.com/simongonzalezdc/complyos/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/badge/license-BUSL--1.1-orange.svg)](LICENSE)

**L&D Compliance & Learning Operations MCP Server**

An AI-native compliance auditing engine for enterprise learning management systems. Built by someone who spent 12 years in L&D ops and got tired of explaining to regulators why the CSV export didn't match the dashboard.

---

## Why ComplyOS?

Enterprise compliance tracking is a disaster of CSV exports, stale dashboards, and "I thought they completed that" moments. ComplyOS treats compliance as a **first-class engineering problem**:

- **Evidence-backed audits** — Every report includes a SHA256-hashed evidence ledger
- **Assignment rule validation** — Test targeting rules before they hit 10,000 users
- **AI-native interface** — Query status via Claude Code, Cursor, or any MCP client
- **Local-first** — SQLite by default; no SaaS lock-in

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
                    │ CSV / Mock  │            │   Workday      │  │  SAP/CSOD│
                    │ Connectors  │            │   Connector    │  │ (future) │
                    └─────────────┘            └────────────────┘  └──────────┘
```

---

## Quick Start

### Installation

```bash
# Clone the repo
git clone https://github.com/simongonzalezdc/complyos.git
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
| CSV export (any LMS) | ✅ Supported | None |
| Workday Learning | ✅ Supported | Basic Auth (env vars) |
| Mock (seed data) | ✅ Built-in | None |
| SAP SuccessFactors | Future scale-out | OAuth 2.0 |
| Cornerstone OnDemand | Future scale-out | OAuth 2.0 |

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

Every audit produces an `EvidenceLedgerEntry` with SHA256 hashes for regulator-ready audit trails.

---

## Roadmap

- [x] Phase 1 — Core auditor, MCP server, CLI, Workday connector, tests
- [x] Phase 2 — SQLite persistence, assignment rules engine, sync command
- [x] Phase 3 — Remediation workflows, CSV connector, compliance digest, HTML dashboard
- [ ] Phase 4 — Operator-ready release: scheduled audit runs, Slack/Teams notifications, release packaging, and documentation/security polish
- [ ] Phase 5 — Scale-out: PostgreSQL backend, live web dashboard, SAP SuccessFactors connector, Cornerstone connector

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
