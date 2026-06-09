# ComplyOS

L&D Compliance & Learning Operations MCP Server

An AI-native compliance auditing tool for enterprise learning management systems.

## Features

- **Compliance Gap Auditor** — Find users missing required training with evidence-backed reports
- **Assignment Rule Validator** — Test workflows before they affect thousands of users
- **Forensic Tracer** — Trace exactly how any assignment happened
- **Audit Report Generator** — Regulator-ready reports with proof ledgers
- **MCP Server** — Query compliance status from Claude Code, Cursor, and other AI agents
- **Local-First** — All data stays in local SQLite by default

## Quick Start

```bash
pip install complyos
```

Run the MCP server:
```bash
complyos mcp
```

Or use the CLI:
```bash
complyos audit
complyos report --department Engineering
complyos status --user u123
```

## Supported LMS Platforms

- Workday Learning
- SAP SuccessFactors (planned)
- Cornerstone OnDemand (planned)

## License

Apache-2.0
