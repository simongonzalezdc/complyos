# Release checklist

Use this checklist before tagging, pushing, opening a Forgejo PR, or publishing an operator-facing ComplyOS release.

## Source-of-truth checks

- Forgejo is the source-of-truth remote. Do not push ComplyOS changes to GitHub unless explicitly approved as a mirror/export.
- Before any public PR, issue, comment, release, or shared artifact, run a public leak audit. Do not publish local usernames, absolute home paths, private emails, tokens, tenant records, webhook URLs, database URLs, or unrelated environment details.
- Prefer GitHub/Forgejo noreply-style author metadata for public commits when available.

## Validation commands

```bash
git diff --check
uv run --extra dev ruff check complyos tests
uv run --extra dev mypy complyos
uv run --extra dev pytest -q
uv run --extra dev pytest tests/unit/test_no_false_compliance_claims.py -q
rm -rf dist && uv build && rm -rf dist
```

## Operator checks

- Confirm `LICENSE` is BUSL-1.1 and the change-date language still matches the intended source-available posture.
- Confirm `SECURITY.md` is present.
- Run `complyos release-check --json`.
- Run `complyos readiness --json`.
- Run `complyos connectors --profile workforce --json`.
- Run `complyos connectors --profile campus --json`.
- Run one CSV smoke audit for workforce and one for campus fixtures.
- Run `complyos security evidence --period current --json` and attach real receipts separately.
- Run `complyos governance packet --lane workforce --json` or `--lane campus` for the target buyer lane.
- Dry-run retention before apply: `complyos privacy retention run --dry-run --json`.
- Confirm no generated dashboard/report includes private production records before publishing it.
- Confirm Slack, Teams, SMTP, OAuth, database, Forgejo, and tenant tokens are provided through environment variables or secret stores, not committed config.

## Claim checks

Allowed public language: readiness, control mapping, evidence-backed audit trail, designed for auditor/counsel review.

Blocked unless reviewed artifacts authorize the exact wording: certification/legal-status claims, automated employment decisioning, background screening, bias-free AI, or school/privacy compliance guarantees.

## Packaging checks

- Build an sdist and wheel with `uv build`.
- Install the wheel into a clean virtual environment before distributing it.
- Keep PostgreSQL drivers optional unless a deployment target needs them.
