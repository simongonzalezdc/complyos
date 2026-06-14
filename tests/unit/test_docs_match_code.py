"""Guard: numeric claims in public docs must match the code they describe.

Regression guard for a recurring drift — the web shell's module count was once
stated as "8" across several docs while ``shell.py`` actually had 9 live modules,
and the same class of drift hit the permission catalog (29 vs 30) and the service
count (15+ vs 15). Memory notes inform; only a test enforces.

This does NOT force every doc to cite a count. It asserts that any explicit
"<n> modules / permissions / services" claim in a public doc equals the value
*derived from the code*. Counts are parsed from source text (not imported), so
the guard does not depend on optional runtime deps (e.g. fastmcp) being
installed in the runner.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PUBLIC_DOCS = [
    "README.md",
    "CONTEXT.md",
    "ARCHITECTURE.md",
    "docs/index.html",
    "docs/compliance-readiness.md",
    "docs/agent-surface.md",
    "docs/enterprise-hardening-report.md",
]

_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30,
}
_NUM = r"\d+|" + "|".join(_WORDS)


def _to_int(token: str) -> int:
    token = token.lower()
    return int(token) if token.isdigit() else _WORDS[token]


def _stated_counts(text: str, noun: str) -> list[int]:
    """Return every count stated as '<n> [live|enterprise] <noun>' in ``text``.

    Matches '9 modules', 'Nine live modules', '30-permission', '15 services'.
    The number and noun must be adjacent (one optional size adjective allowed),
    which keeps unrelated numbers elsewhere in a sentence from matching.
    """
    rx = re.compile(
        r"\b(" + _NUM + r")[ -](?:(?:live|enterprise|active)[ -])?" + noun,
        re.IGNORECASE,
    )
    return [_to_int(m.group(1)) for m in rx.finditer(text)]


# --- counts derived from code (parsed, not imported) ------------------------


def _shell_module_count() -> int:
    src = (ROOT / "complyos/web/shell.py").read_text(encoding="utf-8")
    block = re.search(r"MODULES[^=]*=\s*\((.*?)\n\)", src, re.S)
    assert block, "could not locate the MODULES tuple in shell.py"
    return len(re.findall(r'"key"\s*:', block.group(1)))


def _permission_count() -> int:
    src = (ROOT / "complyos/services/context.py").read_text(encoding="utf-8")
    return len(re.findall(r'^PERM_[A-Z0-9_]+\s*=\s*["\']', src, re.M))


def _service_count() -> int:
    n = 0
    for path in (ROOT / "complyos/services").glob("*.py"):
        src = path.read_text(encoding="utf-8")
        n += len(re.findall(r"^class \w+Service\b", src, re.M))
        n += len(re.findall(r"^class ConnectorRegistry\b", src, re.M))
    return n


def _assert_docs_match(noun: str, expected: int) -> None:
    for rel in PUBLIC_DOCS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        for stated in _stated_counts(text, noun):
            assert stated == expected, (
                f"{rel}: states {stated} {noun} but the code has {expected}. "
                f"Update the doc (or the code) so the count matches."
            )


# --- the guards -------------------------------------------------------------


def test_doc_module_counts_match_shell() -> None:
    _assert_docs_match(r"modules?\b", _shell_module_count())


def test_doc_permission_counts_match_catalog() -> None:
    _assert_docs_match(r"permissions?\b", _permission_count())


def test_doc_service_counts_match_code() -> None:
    _assert_docs_match(r"services?\b", _service_count())


# --- the guard guards itself (a gate that always passes isn't checking) ------


def test_guard_detects_drift() -> None:
    real = _shell_module_count()
    wrong = real - 1
    # A doc claiming a stale count must be caught by _stated_counts.
    found = _stated_counts(f"the shell has {wrong} live modules today", r"modules?\b")
    assert found == [wrong]
    assert wrong != real  # so _assert_docs_match would raise on this text


def test_code_counts_are_sane() -> None:
    # Sanity floor: parsing produced plausible, non-zero values.
    assert _shell_module_count() >= 5
    assert _permission_count() >= 20
    assert _service_count() >= 10
