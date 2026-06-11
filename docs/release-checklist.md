# Release checklist

Use this checklist before tagging or publishing an operator-facing ComplyOS
release.

## Validation commands

```bash
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy complyos --ignore-missing-imports
rm -rf dist && uv build && rm -rf dist
```

## Operator checks

- Confirm `LICENSE` is BUSL-1.1 and the change-date language still matches the
  intended source-available posture.
- Confirm `SECURITY.md` is present.
- Run `complyos release-check --json`.
- Run `complyos connectors --profile workforce --json`.
- Run `complyos connectors --profile campus --json`.
- Run one CSV smoke audit for workforce and one for campus fixtures.
- Confirm no generated dashboard includes private production records before
  publishing it.
- Confirm Slack, Teams, SMTP, OAuth, and database secrets are provided through
  environment variables or secret stores, not committed config.

## Packaging checks

- Build an sdist and wheel with `uv build`.
- Install the wheel into a clean virtual environment before distributing it.
- Keep PostgreSQL drivers optional unless a deployment target needs them.
