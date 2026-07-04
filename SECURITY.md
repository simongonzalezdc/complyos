# Security Policy

ComplyOS handles learning records, workforce metadata, and audit evidence. Treat
all production data as confidential.

## Supported Versions

ComplyOS is pre-1.0. Security fixes land on the default branch and the latest
source-available release.

## Reporting a Vulnerability

Report suspected vulnerabilities privately to PuenteWorks LLC (the licensor)
at `simon@puenteworks.com`. Do not file public issues containing secrets,
webhook URLs, tenant URLs, access tokens, sample employee records, or student
records.

## Secret Handling

- Do not commit SMTP passwords, Slack webhook URLs, Teams workflow URLs, OAuth
  client secrets, database URLs, or tenant-specific API tokens.
- Prefer environment variables or `${VAR}` placeholders in `complyos.yaml`.
- Rotate a webhook or API token immediately if it appears in logs, screenshots,
  traces, public branches, or support tickets.

## Data Handling

- Use CSV fixtures only with synthetic or approved demo data.
- Store local SQLite files and dashboard exports outside public web roots unless
  the report is explicitly intended for publication.
- Use PostgreSQL TLS and least-privilege database users in shared environments.
