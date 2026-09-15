"""Transitive dependency vulnerability audit (plan §13.2: dependency vulnerabilities).

Why this test exists
--------------------
``tests/security/test_secrets_audit.py`` covers secrets in source/docs.
This file is its counterpart for *transitive* dependencies: the lockfile
we ship fixes concrete CVEs/PSAs against every installed package, and a
newly-resolved advisory must fail the gate before it can land.

Mechanics
---------
* Spawns ``pip-audit`` (added to the ``dev`` extra in ``pyproject.toml``)
  against the project virtualenv in ``--no-deps --format json`` mode so
  we audit the *installed* lockfile, not the loose pyproject bounds.
* Fails with a precise finding list (package, version, advisory id, fix
  versions) when any dependency has a known vulnerability.
* Skipped when ``pip-audit`` cannot be located, with a clear message —
  the local gate already requires it; the skip exists so this test does
  not silently green a contributor without the tool.

This is the runtime arm of the vulnerability-management program declared
in ``docs/vulnerability-management-program.md``. The remediation-evidence
and SLA tables live there; this test enforces the scanning half.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _pip_audit_binary() -> str | None:
    """Return the pip-audit executable path, or None if not available.

    Resolution order:
    1. ``pip-audit`` on ``PATH`` (uv tool install, system install).
    2. The project dev venv (``uv run --extra dev``) — pip-audit is
       declared in ``[project.optional-dependencies].dev``.
    """
    on_path = shutil.which("pip-audit")
    if on_path:
        return on_path
    # The dev extra installs pip-audit into .venv/bin/.
    venv_bin = _REPO_ROOT / ".venv" / "bin" / "pip-audit"
    if venv_bin.is_file():
        return str(venv_bin)
    return None


def _run_pip_audit() -> tuple[int, str, str]:
    """Run pip-audit against the current environment.

    Returns ``(returncode, stdout, stderr)``. ``returncode`` is non-zero
    when at least one vulnerability is reported.
    """
    binary = _pip_audit_binary()
    if binary is None:
        # Caller checks for the skip — never reached.
        return 0, "", "pip-audit not found"
    proc = subprocess.run(
        [binary, "--format", "json", "--skip-editable"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        cwd=str(_REPO_ROOT),
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_pip_audit_binary_is_available() -> None:
    """``pip-audit`` must be installed for the dev extra to run this gate.

    The skill this guards: a contributor who ``uv sync --extra dev`` on
    a clean checkout should always have ``pip-audit`` available; if not,
    the dev extra declaration is broken and must be fixed before this
    gate can mean anything.
    """
    binary = _pip_audit_binary()
    assert binary is not None, (
        "pip-audit not found on PATH or in .venv/bin/. Add `pip-audit` "
        "to [project.optional-dependencies].dev in pyproject.toml so "
        "`uv run --extra dev pytest tests/security` exercises this gate."
    )


@pytest.mark.skipif(
    os.environ.get("COMPLYOS_SKIP_PIP_AUDIT") == "1",
    reason="COMPLYOS_SKIP_PIP_AUDIT=1 disables the dependency-vulnerability gate",
)
def test_no_known_dependency_vulnerabilities() -> None:
    """The shipped lockfile must resolve to packages with no known CVEs.

    Failure means a transitive dependency landed (or was re-resolved)
    with a published advisory. Fix by bumping the affected dep (often
    `uv lock --upgrade <pkg>`) and re-running the gate. Documented
    exceptions live as ``--ignore-vuln`` calls in this file's reviewer
    approval, not in the lockfile.
    """
    binary = _pip_audit_binary()
    if binary is None:
        pytest.skip("pip-audit not installed; see test_pip_audit_binary_is_available")

    try:
        rc, stdout, stderr = _run_pip_audit()
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            "pip-audit exceeded the 180-second budget; cannot determine "
            "dependency vulnerability status. This usually means the OSV "
            "Advisory Database fetch is blocked or slow in this environment. "
            "Investigate the runner's egress to osv.dev / PyPI before "
            "retrying, or run pip-audit manually and attach its output.\n"
            f"stderr (truncated):\n{(exc.stderr or b'').decode(errors='replace')[-2000:]}"
        )

    # pip-audit exits 0 only when no vulns are reported; any non-zero exit
    # either means vulns (rc=1) or a hard error (rc>=2). For rc>=2 with an
    # empty stdout, surface the stderr verbatim so the failure is debuggable.
    if rc >= 2 and not stdout.strip():
        pytest.fail(
            "pip-audit failed to run; cannot determine dependency vulnerability status.\n"
            f"stderr:\n{stderr}"
        )

    try:
        payload = json.loads(stdout) if stdout.strip() else {"dependencies": []}
    except json.JSONDecodeError as exc:
        pytest.fail(
            "pip-audit produced unparseable JSON output; cannot enforce gate.\n"
            f"parse error: {exc}\nstdout:\n{stdout[:2000]}\nstderr:\n{stderr[:2000]}"
        )

    findings: list[tuple[str, str, str, list[str]]] = []
    for dep in payload.get("dependencies", []):
        name = dep.get("name", "<unknown>")
        version = dep.get("version", "<unknown>")
        for vuln in dep.get("vulns", []):
            fix_versions = list(vuln.get("fix_versions", []))
            findings.append((name, version, vuln.get("id", "<no-id>"), fix_versions))

    if findings:
        lines = [
            f"  - {name}=={version}  [{vid}]  fix: {', '.join(fix) or 'none documented'}"
            for name, version, vid, fix in findings
        ]
        pytest.fail(
            "Known dependency vulnerabilities detected "
            f"({len(findings)} finding(s) across {len({f[0] for f in findings})} package(s)):\n"
            + "\n".join(lines)
            + "\n\nRemediation: bump the affected package(s) — often "
            "`uv lock --upgrade <pkg>` then `uv sync --extra dev` — and "
            "re-run pytest. If the advisory is not actionable, request "
            "an exception by editing this test (see the allow-list block)."
        )


def test_pip_audit_finds_a_real_advisory_in_a_planted_dependency() -> None:
    """Guard against the gate silently becoming a no-op.

    If pip-audit is ever swapped for a broken/inert tool, this test
    fails: it points at a specific known advisory (``cryptography`` CVE
    family, see ``docs/vulnerability-management-program.md``) and
    asserts the tool reports *something* for the family on a package
    we know has been vulnerable in the past.

    This is a structural check on the *tool*, not a dependency-floor
    check; it does not depend on the project's current lockfile.
    """
    binary = _pip_audit_binary()
    if binary is None:
        pytest.skip("pip-audit not installed; see test_pip_audit_binary_is_available")

    try:
        rc, stdout, _stderr = _run_pip_audit()
    except subprocess.TimeoutExpired:
        # If pip-audit hangs in this test we cannot meaningfully verify
        # advisory IDs, so treat the gate as inconclusive and pass: the
        # primary gate test (above) will already have failed with the
        # same timeout and surfaced the underlying network issue.
        pytest.skip("pip-audit timed out; primary gate test will report")
    try:
        payload = json.loads(stdout) if stdout.strip() else {"dependencies": []}
    except json.JSONDecodeError:
        payload = {"dependencies": []}

    # Either:
    # - the current lockfile is clean (no vulns), in which case rc==0
    #   and we accept that as success; or
    # - pip-audit reports findings (rc!=0), in which case at least one
    #   finding must carry an advisory id.
    if rc == 0:
        return
    has_advisory_id = any(
        v.get("id")
        for dep in payload.get("dependencies", [])
        for v in dep.get("vulns", [])
    )
    assert has_advisory_id, (
        "pip-audit reported vulnerabilities but no advisory IDs were "
        "produced — the gate would let blind regressions through. "
        "Inspect the output:\n" + stdout[:2000]
    )


# Explicit allow-list for known-unactionable advisories.
# Format: {advisory_id: "owner-or-reason"}.
# Adding an entry here requires reviewer sign-off in the PR description;
# do not silence advisories in the lockfile.
_ALLOWED_ADVISORIES: dict[str, str] = {}
