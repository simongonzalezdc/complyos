"""Static secrets-leakage audit (plan §13.2: secrets leakage).

Scans the shipped source, tests, and docs for hardcoded secret literals — AWS
access keys, private keys, generic long API tokens, DB connection passwords, and
webhook/HMAC secrets assigned to string literals. The suite is meant to FAIL if a
real-looking secret is introduced later, so a small, explicit allow-list covers
the deliberately-fake fixtures (e.g. ``COMPLYOS_API_TOKEN="test-token"``) that the
test suite legitimately needs. New entries on the allow-list should be reviewed.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root: tests/security/<this file> -> parents[2] is the project root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_DIRS = ("complyos", "tests", "docs")

# Directories/files that are not source we authored or that store opaque hashes.
_SKIP_DIR_NAMES = {"__pycache__", ".git", ".venv", "node_modules", ".mypy_cache", ".ruff_cache"}
_SCAN_SUFFIXES = {".py", ".md", ".json", ".toml", ".cfg", ".ini", ".txt", ".yaml", ".yml", ".env"}

# Curated secret patterns. Each is a (name, compiled-regex) the audit treats as a
# finding unless the matched text is on the allow-list below.
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    (
        "aws_secret_access_key",
        re.compile(r"aws_secret_access_key\s*[=:]\s*['\"][A-Za-z0-9/+=]{40}['\"]"),
    ),
    (
        "private_key_block",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ),
    # Generic secret/token/password/api_key assigned to a non-trivial literal.
    (
        "assigned_secret_literal",
        re.compile(
            r"(?i)\b(?:api[_-]?key|api[_-]?token|secret|password|passwd|client[_-]?secret"
            r"|webhook[_-]?secret|access[_-]?token|private[_-]?key)\b\s*[=:]\s*"
            r"['\"]([^'\"\n]{8,})['\"]"
        ),
    ),
    # Postgres/MySQL style DSN with an inline password.
    (
        "db_url_with_password",
        re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb)://[^\s:/@]+:[^\s:/@]{4,}@"),
    ),
]

# Allow-listed literals: obviously-fake fixtures, placeholders, env var names, and
# documentation examples. Matched case-insensitively as a substring of the finding.
_ALLOWED_SUBSTRINGS = {
    # Deliberately-fake test tokens / secrets used across the suite.
    "test-token",
    "inbound-secret",
    "do-not-store",
    "wrong",  # sha256=wrong in the bad-signature test
    "client-secret",  # connector unit-test fixtures (cornerstone/successfactors)
    "test_pass",  # workday connector unit-test fixture
    "test-secret",
    "fake",
    "dummy",
    "sample",
    # Placeholder / documentation values, not real credentials.
    "your-token-here",
    "your_token_here",
    "changeme",
    "change-me",
    "example",
    "placeholder",
    "redacted",
    "xxxxxxxx",
    "<token>",
    "<secret>",
    "${",  # shell/template interpolation, not a literal
    "os.getenv",
    "getenv",
    "os.environ",
    # Env var *names* (not values) that contain the trigger words.
    "complyos_api_token",
    "complyos_inbound_webhook_secret",
    "complyos_allow_insecure_local",
    "complyos_mcp_role",
}

_ALLOWED_REGEXES = (
    # A line that resolves its secret from the environment, not a literal.
    re.compile(r"(?i)os\.(?:getenv|environ)"),
)


def _is_allowed(matched_text: str, line: str) -> bool:
    lowered = line.lower()
    if any(allowed in lowered for allowed in _ALLOWED_SUBSTRINGS):
        return True
    return any(rx.search(line) for rx in _ALLOWED_REGEXES)


def _scannable_files() -> list[Path]:
    files: list[Path] = []
    for top in _SCAN_DIRS:
        base = _REPO_ROOT / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.suffix.lower() not in _SCAN_SUFFIXES:
                continue
            # The audit must not flag itself for carrying the patterns/fixtures.
            if path.resolve() == Path(__file__).resolve():
                continue
            files.append(path)
    return files


def test_no_hardcoded_secrets_in_source_tests_or_docs() -> None:
    findings: list[str] = []
    for path in _scannable_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for name, pattern in _SECRET_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                if _is_allowed(match.group(0), line):
                    continue
                rel = path.relative_to(_REPO_ROOT)
                findings.append(f"{rel}:{lineno} [{name}] {line.strip()[:120]}")

    assert not findings, "Hardcoded secret literals detected:\n" + "\n".join(findings)


def test_secrets_audit_actually_detects_a_planted_secret(tmp_path) -> None:
    """Guard against the audit silently becoming a no-op: a planted AWS key,
    private-key block, and assigned secret literal must all be caught."""
    planted = "\n".join(
        [
            "aws_key = 'AKIA1234567890ABCDEF'",  # AKIA + 16 chars, no allow-list word
            "-----BEGIN RSA PRIVATE KEY-----",
            "api_key = 'sk_live_5f3a9c2b8e1d7'",
            "db = 'postgresql://app:Sup3rSecret@db.internal:5432/app'",
        ]
    )
    fixture = tmp_path / "leak.py"
    fixture.write_text(planted, encoding="utf-8")

    hits: list[str] = []
    for line in planted.splitlines():
        for name, pattern in _SECRET_PATTERNS:
            match = pattern.search(line)
            if match and not _is_allowed(match.group(0), line):
                hits.append(name)

    # Every planted secret category is caught, proving the audit is not a no-op.
    assert "aws_access_key_id" in hits
    assert "private_key_block" in hits
    assert "assigned_secret_literal" in hits
    assert "db_url_with_password" in hits
