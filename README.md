# ComplyOS

[![Source of truth](https://img.shields.io/badge/source-Forgejo-609966.svg)](#source-of-truth)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License](https://img.shields.io/badge/license-BUSL--1.1-orange.svg)](LICENSE)

**HR/L&D compliance operations and learning-evidence MCP/API/CLI toolkit**

ComplyOS is a Python (3.11+) toolkit that transforms HRIS, LMS, and CSV learning records into tenant-scoped evidence, gap reports, DSR workflows, retention cleanup, and readiness packets for HR, People Ops, L&D, security, and campus teams. It provides compliance automation through evidence-backed audits, import governance, and privacy workflows, accessible via API, CLI, MCP, and an authenticated web shell.

## What is this?

ComplyOS is **readiness/control-mapping software**—not a certification badge or automated employment-decision system. It treats compliance as an evidence problem, ensuring every audit, report, and workflow is backed by verifiable, tenant-scoped data.

ComplyOS is the **live compliance/evidence module** inside the working-title [LearningOps Suite](docs/learningops-suite-v0.md): a modular HR/L&D automation suite for intake, rosters, scheduling, regulatory awareness, instructional design, training specialist workflows, microlearning, evaluation, and manager briefs.

Regulatory awareness is powered by [RegWatch v0](docs/regwatch-v0.md): official source monitoring, source provenance, coverage-gap disclosure, and human-approved proposals before any rule, training, or notification changes state. The Source Intelligence spine includes DB-backed schedules, job execution receipts, review UI, API/CLI export packets, and local fallbacks so external API procurement does not block hardening.

## Table of Contents
- [Features](#features)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Architecture](#architecture)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

## Features

ComplyOS provides a comprehensive suite for compliance automation and HR technology workflows:

- **Evidence-backed audits** — Reports cite tenant-scoped SHA256 evidence entries and action logs for full auditability.
- **Import governance** — Preview, quarantine, and promote CSV rows with a controlled pipeline instead of allowing bad exports to mutate source data.
- **Privacy & data-subject workflows** — Create DSR cases, require controller approval, block deletion on legal hold, and run dry-run retention cleanup.
- **Security & governance packets** — Collect readiness-only SOC 2-style control evidence, AI boundary assessments, school vendor packets, and FCRA employment-decision boundary documentation.
- **Source-intelligence review spine** — Schedule local checks, store review proposals, decide them through RBAC, and export audit packets before any downstream change.
- **Notification outbox, email, and signed hooks** — Queue deliveries with payload hashes, retry state, dry-run drain, channel/event kill switches, and HMAC headers.
- **Authenticated web shell** — Nine live modules (Overview, Gaps, Imports, Evidence, Remediation, Source intelligence, Privacy & retention, Readiness, Administration) at `/shell` with signed-session cookie auth, reading real service data. Enforced **WCAG 2.2 AA accessibility** compliance via tests.
- **Proposal-only AI layer** — AI can suggest field mappings, anomaly summaries, gap explanations, remediation drafts, and duplicate clusters, but **cannot** mutate compliance state. PII is redacted before hashing; every proposal has reject/expiry lifecycle and full provenance.
- **Agent-native surfaces** — Use the same service-backed workflows through CLI, API v1, MCP tools, or the web shell.
- **Local-first** — SQLite by default, with PostgreSQL-ready URLs for production deployment.
- **Enterprise hardening** — Includes security fixes like cross-tenant IDOR protection, adversarial test suite (BOLA/IDOR, injection, denial), and controlled migration/rollback procedures.

## Installation

### Prerequisites
- Python 3.11 or higher
- `uv` (recommended) or `pip`

### Install with uv (Recommended)
```bash
git clone <forgejo-complyos-remote>
cd complyos
uv sync --all-extras --dev
```

### Install with pip
```bash
git clone <forgejo-complyos-remote>
cd complyos
pip install -e ".[dev]"
```

### Verify Installation
```bash
complyos --version
```

## Quick Start

### 1. Initialize a Profile
```bash
# Workforce profile (HRIS-focused)
complyos init --profile workforce

# Campus profile (academic-focused)
complyos init --profile campus --output campus.yaml
```

### 2. Run an Audit
```bash
# Basic compliance audit
complyos audit

# Filtered audit by department
complyos audit --department Engineering

# Generate structured JSON report
complyos report --department Engineering --json
```

### 3. Serve the Web Interface
```bash
# Start the authenticated web shell and API
complyos serve-dashboard --host 127.0.0.1 --port 8000

# Access the shell in your browser
# http://127.0.0.1:8000/shell
# Login with your API token
```

### 4. Manage Notifications
```bash
# List pending notification events
complyos notifications list --db complyos.db --json

# Drain the notification outbox (dry-run)
complyos notifications drain --db complyos.db --dry-run --json

# Send notifications
complyos notifications drain --db complyos.db --send --json
```

## Usage

### Core CLI Commands

#### Compliance Operations
```bash
# Check a single user's compliance status
complyos status u1

# Get a digest of changes since the last audit (new/resolved gaps, trend)
complyos digest

# Generate an interactive HTML dashboard
complyos dashboard --open

# Run scheduled audits (for cron/systemd/Forgejo Actions)
complyos run-schedule --config complyos.yaml
```

#### Data Management
```bash
# Inspect connector capabilities for a profile
complyos connectors --profile workforce --json

# Run release-readiness checks
complyos release-check --json

# Collect readiness/control packets for review
complyos readiness export --json
```

### API v1 (FastAPI)
The API is available at `/api/v1` when the server is running. Key endpoints include:
- `GET /api/v1/audit` — Run compliance audits
- `GET /api/v1/report` — Generate reports
- `POST /api/v1/privacy/dsr` — Create data-subject requests
- `GET /api/v1/notifications/outbox` — Manage notifications

### MCP Tools (FastMCP)
ComplyOS exposes the same service workflows as MCP tools for AI agent integration, enabling programmatic access to compliance operations.

### Web Shell
Access the authenticated web interface at `/shell` for:
- **Dashboard Overview** with real-time compliance metrics
- **Gap Analysis** with drill-down into specific learners and requirements
- **Import Management** with quarantine/promote workflows
- **Evidence Collection** for SOC 2 and other readiness packets
- **Privacy & Retention** management with DSR workflows
- **Source Intelligence** for regulatory monitoring and proposal review
- **Administration** for tenant settings and user permissions

All modules read from live service data and enforce RBAC permissions.

## Architecture

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│  CLI (Typer) │  │  API v1      │  │  MCP         │  │  Web shell       │
│  complyos *  │  │  FastAPI     │  │  FastMCP     │  │  /shell (cookie) │
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘
       │                 │                 │                    │
       └─────────────────┴─────────────────┴────────────────────┘
                                   │
                    ┌──────────────▼──────────────────┐
                    │   Application SERVICE layer      │
                    │  ActorContext + require_perm(*)  │
                    │  (AuditService, EvidenceService, │
                    │   ImportService, PrivacySvc, …)  │
                    └──────┬──────────────┬────────────┘
                           │              │
              ┌────────────▼───┐   ┌──────▼───────────────────────┐
              │  Auditor /     │   │  LocalRepository (mixins)    │
              │  Rules engine  │   │  core | privacy | notif |    │
              └────────────────┘   │  source-intel | import | ORM │
                                   └──────────────┬───────────────┘
                                                  │
                    ┌─────────────────────────────┴──────────────────┐
                    │               Connectors                        │
                    │  CSV  │  Workday  │  SAP SuccessFactors  │ CSOD │
                    └────────────────────────────────────────────────┘
```

### Tenant Model
ComplyOS runs **single-tenant at runtime** with a **tenant-aware data model**: every persisted row carries a `tenant_id` so the schema is ready for migration without backfills. Multi-tenant/SaaS hosting is not built. See [docs/multi-tenancy.md](docs/multi-tenancy.md) for the full posture.

### Security Posture
- **Cross-tenant IDOR protection** with explicit permission checks on all service methods
- **Adversarial test suite** covering BOLA/IDOR, injection, denial, and export attacks
- **Proposal-only AI layer** with PII redaction and prompt-injection guards
- **Migration/rollback procedures** documented for safe deployments

## FAQ

### How does ComplyOS handle data privacy and GDPR compliance?
ComplyOS includes built-in data-subject request (DSR) workflows, configurable data retention policies, and privacy impact assessments. All PII in AI proposals is redacted before processing. See the [privacy data map](docs/privacy-data-map.md) and [data-subject request workflow](docs/data-subject-request-workflow.md) for details.

### Can I use ComplyOS with my existing HRIS/LMS systems?
Yes. ComplyOS supports CSV imports and has connector interfaces for Workday, SAP SuccessFactors, CSOD, and other systems. The connector capability matrix is profile-specific—run `complyos connectors --profile yourprofile` to see what's supported.

### Is the AI layer compliant with AI governance requirements?
The AI layer is designed as "proposal-only" with strict guards: it cannot mutate compliance state, all suggestions have reject/expiry lifecycles, and full provenance is tracked. This aligns with [AI governance impact assessments](docs/ai-governance-impact-assessment.md).

### How do I handle regulatory changes?
RegWatch v0 monitors official sources and creates human-approved proposals before any rule changes. This ensures changes go through proper review and approval workflows.

### What's the difference between the web shell and API?
The web shell provides a visual interface for all workflows with real-time dashboards, while the API provides programmatic access for integration with other systems. Both use the same service layer and permissions.

### How is accessibility handled?
The web shell enforces WCAG 2.2 AA compliance through automated contrast audits and accessibility tests. This ensures the interface is usable for people with disabilities.

## Contributing

We welcome contributions to ComplyOS! Please follow these guidelines:

1. **Code Quality**: Follow the existing code style. We use Ruff for linting and formatting.
   ```bash
   ruff check .
   ruff format .
   ```

2. **Testing**: Write tests for new features and ensure existing tests pass.
   ```bash
   pytest
   pytest --cov=complyos --cov-report=html
   ```

3. **Documentation**: Update relevant documentation for any feature changes, especially in the `docs/` directory.

4. **Pull Requests**: 
   - Keep PRs focused on single features or fixes
   - Reference related issues
   - Ensure all CI checks pass
   - Update the CHANGELOG if applicable

5. **Commit Messages**: Use conventional commits format.

6. **Architecture Decisions**: For significant changes, document your rationale in an [ADR](docs/adr/).

Please review our [SECURITY.md](SECURITY.md) for security-related contributions and [AGENTS.md](AGENTS.md) for agent-related work.

## License

ComplyOS is licensed under the [Business Source License 1.1](LICENSE).

This means:
- You can use, modify, and distribute the software
- You cannot use it to offer a competing hosted/managed service
- After 4 years, the license converts to a permissive open-source license (Apache 2.0 or similar)
- See the LICENSE file for the complete terms

The BUSL-1.1 license allows free use while protecting the project's sustainability. For commercial use beyond the license terms, please contact the repository owner.

---

**Source of truth**: Forgejo is the source-of-truth remote for ComplyOS. Do not push changes to GitHub unless the repository owner explicitly asks for a mirror or legacy export.

**Demo packets** are synthetic and explicitly labeled:
- [Training from scratch](docs/demos/training-from-scratch.md)
- [Fix messy existing training operations](docs/demos/fix-messy-training-ops.md)

**Design direction** is captured in [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md).