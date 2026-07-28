# ComplyOS

[![Source of truth](https://img.shields.io/badge/source-Forgejo-609966.svg)](source-of-truth) [![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/) [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)]

## Quick start

```bash
# Clone the private Forgejo remote you were granted (see "Getting the source")
git clone <your-granted-forgejo-remote> complyos
cd complyos
# Install with uv (recommended)
uv sync --all-extras --dev
# Or with pip
pip install -e ".[dev]"
```

```bash
# Run tests
uv run --extra dev pytest -q
# Run with coverage
uv run --extra dev pytest --cov=complyos --cov-report=term-missing
# Lint
uv run --extra dev ruff check .
# Type check
uv run --extra dev mypy complyos
```

## Docs

- [LearningOps Suite](docs/learningops-suite-v0.md)
- [RegWatch v0](docs/regwatch-v0.md)
- [Training from scratch](docs/demos/training-from-scratch.md)
- [Fix messy existing training operations](docs/demos/fix-messy-training-ops.md)
- [DESIGN-SYSTEM.md](DESIGN-SYSTEM.md)

## License

See [LICENSE](LICENSE).
