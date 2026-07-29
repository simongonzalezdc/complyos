# ComplyOS

HR/L&D compliance operations toolkit (MCP, API, CLI, web shell). Turns HRIS/LMS/CSV learning records into tenant-scoped evidence, gap reports, DSR workflows, retention cleanup, and readiness packets.

**Who it is for:** HR, People Ops, L&D, security, and campus teams who need evidence-backed learning compliance — not a certification badge or automated employment-decision system.

**What you get:** local-first compliance/evidence workflows with import governance, privacy cases, readiness packets, and agent surfaces (CLI / API v1 / MCP / authenticated web shell).

## Why it wins

- Evidence-backed audits with tenant-scoped hashes and action logs
- Import preview/quarantine/promote instead of silent CSV mutation
- DSR + retention dry-runs with legal-hold blocks
- Proposal-only AI (suggests; never marks compliance or promotes imports)
- SQLite by default; PostgreSQL-ready when needed

## Quick start

```bash
git clone https://github.com/simongonzalezdc/complyos.git
cd complyos
# Python 3.11+ — follow package/CLI install in-tree
pip install -e .
complyos --help
```

LearningOps suite context (maturity-labeled): [docs/learningops-suite-v0.md](docs/learningops-suite-v0.md). RegWatch v0: [docs/regwatch-v0.md](docs/regwatch-v0.md).

## Docs

- [LearningOps suite v0](docs/learningops-suite-v0.md)
- [RegWatch v0](docs/regwatch-v0.md)
- [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md)
- Demo packets (synthetic, labeled): [training from scratch](docs/demos/training-from-scratch.md), [fix messy training ops](docs/demos/fix-messy-training-ops.md)

## License

See [LICENSE](LICENSE) (BUSL-1.1 badge on historical face).
