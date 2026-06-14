"""Accessibility + visual-correctness audit for the enterprise shell (WP16d).

This is a real audit, not a smoke test. For every live module it renders the
authenticated page and enforces WCAG 2.2 AA *structure* (one main landmark, a
skip link, labelled nav, captioned/scoped tables, named form controls, a
non-generic title). It then computes *real* WCAG contrast ratios from the hex
pairs declared in ``shell.css`` and asserts the status chips and body text clear
the 4.5:1 threshold for normal text.

The contrast helper is pure Python (sRGB → linear → relative luminance → ratio)
and the HTML is parsed with the stdlib ``html.parser`` — no bs4/lxml, no new
runtime deps. When a pair fails, the fix lives in ``shell.css`` (an accessible
shade inside the DESIGN-SYSTEM palette family) and this test locks it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from complyos.connectors.mock import MockConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.repository import LocalRepository
from complyos.web.dashboard import create_dashboard_app

SHELL_CSS = Path(__file__).resolve().parents[2] / "complyos" / "web" / "static" / "shell.css"


# ---------------------------------------------------------------------------
# Test client helpers (mirror tests/unit/test_shell.py: insecure-local + role).
# ---------------------------------------------------------------------------


def _local_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, db_name: str
) -> tuple[TestClient, LocalRepository]:
    """Insecure-local shell client over a real MockConnector auditor."""
    monkeypatch.delenv("COMPLYOS_API_TOKEN", raising=False)
    monkeypatch.setenv("COMPLYOS_ALLOW_INSECURE_LOCAL", "1")
    repo = LocalRepository(str(tmp_path / db_name))
    auditor = ComplianceAuditor(MockConnector())
    app = create_dashboard_app(auditor=auditor, repository=repo)
    return TestClient(app), repo


def _login_local(client: TestClient, role: str) -> None:
    # Don't follow the redirect to Overview: some roles lack readiness:read,
    # which Overview requires. The cookie is set on the 303 itself, so module
    # routes under test still see an authenticated context.
    client.post("/shell/login", data={"role": role}, follow_redirects=False)


# ---------------------------------------------------------------------------
# WCAG contrast math (pure Python, in-file by design).
# ---------------------------------------------------------------------------


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _channel_to_linear(channel: int) -> float:
    c = channel / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_channel_to_linear(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """WCAG 2.x contrast ratio between two opaque sRGB colors."""
    l1 = _relative_luminance(fg)
    l2 = _relative_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def _composite_over(
    fg: tuple[int, int, int], alpha: float, bg: tuple[int, int, int]
) -> tuple[int, int, int]:
    """Flatten a translucent fill (rgba) over an opaque surface.

    The chip backgrounds are declared as ``rgba(... , alpha)`` and render on top
    of an opaque card/table surface, so the *effective* background a screen
    reader's user actually sees is the alpha-composite, not the raw rgba color.
    """
    return tuple(round(alpha * f + (1 - alpha) * b) for f, b in zip(fg, bg, strict=True))  # type: ignore[return-value]


# Palette, extracted from shell.css / DESIGN-SYSTEM.md. Kept as literals so the
# test fails loudly if a token's hex drifts away from an accessible value.
INK = _hex_to_rgb("#171b18")  # --ink, primary body text
MUTED = _hex_to_rgb("#5b655d")  # --muted, secondary text
PAPER = _hex_to_rgb("#f6f7f1")  # --paper, page background
PAPER_STRONG = _hex_to_rgb("#ffffff")  # --paper-strong, card/table surface
ACCENT_DARK = _hex_to_rgb("#213f2f")  # --accent-dark, chip text
ACCENT_SOFT = _hex_to_rgb("#dbe8dc")  # --accent-soft, opaque chip fill
AMBER = _hex_to_rgb("#b5762b")  # --amber, raw provenance accent
AMBER_INK = _hex_to_rgb("#8a5414")  # --amber-ink, accessible chip text
DANGER = _hex_to_rgb("#7d3f36")  # --danger, risk text

# Translucent fills flattened over both surfaces a chip can sit on.
AMBER_SOFT_ON_WHITE = _composite_over(AMBER, 0.14, PAPER_STRONG)
AMBER_SOFT_ON_PAPER = _composite_over(AMBER, 0.14, PAPER)
DANGER_SOFT_ON_WHITE = _composite_over(DANGER, 0.12, PAPER_STRONG)
DANGER_SOFT_ON_PAPER = _composite_over(DANGER, 0.12, PAPER)

AA_NORMAL = 4.5  # WCAG 2.2 AA, normal-size text (chip labels are ~11px, not large).


# ---------------------------------------------------------------------------
# Stdlib HTML structural audit.
# ---------------------------------------------------------------------------


class _A11yAudit(HTMLParser):
    """Collect the structural facts WCAG cares about from rendered HTML.

    Deliberately tolerant of the (well-formed) shell markup: we track open tags
    on a stack so we can attribute ``<th>`` to its table, decide whether a
    ``<button>`` has visible text, and tell whether an ``<input>`` is wrapped by
    a ``<label>``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.html_attrs: dict[str, str | None] = {}
        self.title: str | None = None
        self.main_count = 0
        self.nav_aria_labels: list[str] = []
        self.skip_link_href: str | None = None
        # Tables: each entry = {"labelled": bool, "ths": [bool scope...]}
        self.tables: list[dict[str, object]] = []
        # Form controls flagged as missing an accessible name.
        self.unlabeled_controls: list[str] = []
        # label[for] targets seen anywhere in the doc.
        self.label_for_targets: set[str] = set()
        # Controls (by their own attrs) that need a label[for] match resolved
        # after parsing: (tag, id, has_intrinsic_name, text_or_value).
        self._deferred: list[tuple[str, str | None, bool]] = []

        self._tag_stack: list[str] = []
        self._in_title = False
        self._label_depth = 0  # >0 while inside a <label> (wrapping label)
        self._button_text: list[str] = []
        self._capturing_button = False
        self._pending_button_unnamed = False

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _attr(attrs: list[tuple[str, str | None]], name: str) -> str | None:
        for key, value in attrs:
            if key == name:
                return value
        return None

    def _has_accessible_name_attr(self, attrs: list[tuple[str, str | None]]) -> bool:
        return bool(
            self._attr(attrs, "aria-label")
            or self._attr(attrs, "aria-labelledby")
            or self._attr(attrs, "title")
        )

    # -- parser hooks -----------------------------------------------------
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag_stack.append(tag)
        adict = dict(attrs)

        if tag == "html":
            self.html_attrs = adict
        elif tag == "title":
            self._in_title = True
        elif tag == "main":
            self.main_count += 1
        elif tag == "nav":
            label = self._attr(attrs, "aria-label") or self._attr(attrs, "aria-labelledby")
            self.nav_aria_labels.append(label or "")
        elif tag == "a":
            href = self._attr(attrs, "href")
            if href == "#main" and self.skip_link_href is None:
                self.skip_link_href = href
        elif tag == "label":
            self._label_depth += 1
            for_target = self._attr(attrs, "for")
            if for_target:
                self.label_for_targets.add(for_target)
        elif tag == "table":
            labelled = self._has_accessible_name_attr(attrs)
            self.tables.append({"labelled": labelled, "ths": [], "caption": False})
        elif tag == "caption" and self.tables:
            self.tables[-1]["caption"] = True
        elif tag == "th" and self.tables:
            ths = self.tables[-1]["ths"]
            assert isinstance(ths, list)
            ths.append(self._attr(attrs, "scope") is not None)
        elif tag in {"input", "select", "textarea", "button"}:
            self._record_control(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "label" and self._label_depth > 0:
            self._label_depth -= 1
        elif tag == "button" and self._capturing_button:
            text = "".join(self._button_text).strip()
            if not text and self._pending_button_unnamed:
                self.unlabeled_controls.append("button")
            self._capturing_button = False
            self._button_text = []
        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title or "") + data
        if self._capturing_button:
            self._button_text.append(data)

    # -- control naming ---------------------------------------------------
    def _record_control(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        control_id = self._attr(attrs, "id")
        ctype = self._attr(attrs, "type")
        # Hidden inputs and submit/button inputs with a value need no label.
        if tag == "input" and ctype in {"hidden", "submit", "reset", "button"}:
            return
        intrinsic = self._has_accessible_name_attr(attrs)
        wrapped = self._label_depth > 0

        if tag == "button":
            # A button's accessible name may be its text content; capture it and
            # decide at the end tag. Buttons with aria-label/title are already named.
            self._capturing_button = True
            self._button_text = []
            self._pending_button_unnamed = not (intrinsic or wrapped)
            return

        if intrinsic or wrapped:
            return
        # Otherwise it needs a <label for> match, resolved after the full parse.
        self._deferred.append((tag, control_id, False))

    def finalize(self) -> None:
        for tag, control_id, _ in self._deferred:
            if control_id and control_id in self.label_for_targets:
                continue
            self.unlabeled_controls.append(f"{tag}#{control_id or '(no id)'}")


def _audit_html(html: str) -> _A11yAudit:
    parser = _A11yAudit()
    parser.feed(html)
    parser.finalize()
    return parser


# ---------------------------------------------------------------------------
# Per-module structural audit.
# ---------------------------------------------------------------------------

# (path, login role, db file) for every live module. Each role is chosen so the
# module renders its full content, not the inline permission-denied panel.
_MODULES: list[tuple[str, str, str]] = [
    ("/shell", "compliance_manager", "a11y-overview.db"),
    ("/shell/gaps", "compliance_manager", "a11y-gaps.db"),
    ("/shell/imports", "importer", "a11y-imports.db"),
    ("/shell/evidence", "compliance_manager", "a11y-evidence.db"),
    ("/shell/remediation", "compliance_manager", "a11y-remediation.db"),
    ("/shell/source-intel", "compliance_manager", "a11y-source-intel.db"),
    ("/shell/privacy", "privacy_admin", "a11y-privacy.db"),
    ("/shell/readiness", "compliance_manager", "a11y-readiness.db"),
    ("/shell/admin", "owner", "a11y-admin.db"),
]


@pytest.mark.parametrize(("path", "role", "db_name"), _MODULES, ids=[m[0] for m in _MODULES])
def test_module_passes_structural_a11y_audit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
    role: str,
    db_name: str,
) -> None:
    """Each live module satisfies WCAG 2.2 AA structural requirements."""
    client, _ = _local_client(monkeypatch, tmp_path, db_name)
    _login_local(client, role)

    response = client.get(path)
    assert response.status_code == 200, f"{path} did not render for role {role}"
    # Guard against silently auditing the permission-denied fallback instead of
    # the real module (which would make the rest of the assertions meaningless).
    assert "do not have permission" not in response.text.lower(), (
        f"{path} rendered the denial panel for role {role}; pick a higher role"
    )

    audit = _audit_html(response.text)

    # 1. Language is declared.
    assert audit.html_attrs.get("lang") == "en", f"{path}: <html lang=\"en\"> missing"

    # 2. Exactly one main landmark + an early skip-to-content link.
    assert audit.main_count == 1, f"{path}: expected exactly one <main>, got {audit.main_count}"
    assert audit.skip_link_href == "#main", f"{path}: skip-to-content link missing"

    # 3. A nav with an accessible label.
    assert audit.nav_aria_labels, f"{path}: no <nav> landmark found"
    assert all(label.strip() for label in audit.nav_aria_labels), (
        f"{path}: a <nav> is missing aria-label/aria-labelledby"
    )

    # 4. Every table is named and every header cell is scoped.
    for index, table in enumerate(audit.tables):
        assert table["caption"] or table["labelled"], (
            f"{path}: table #{index} has neither <caption> nor aria-label"
        )
        ths = table["ths"]
        assert isinstance(ths, list)
        assert all(ths), f"{path}: table #{index} has a <th> without a scope attribute"

    # 5. Every interactive control has an accessible name.
    assert not audit.unlabeled_controls, (
        f"{path}: unlabeled form controls: {audit.unlabeled_controls}"
    )

    # 6. A set, non-generic page title.
    assert audit.title and audit.title.strip(), f"{path}: <title> is empty"
    assert audit.title.strip() != "ComplyOS", f"{path}: <title> is the generic fallback"


# ---------------------------------------------------------------------------
# Contrast audit — real WCAG ratios over the chip + body-text pairs.
# ---------------------------------------------------------------------------


def test_primary_body_text_contrast() -> None:
    """Primary and secondary body text clear AA on both surfaces."""
    assert contrast_ratio(INK, PAPER) >= AA_NORMAL
    assert contrast_ratio(INK, PAPER_STRONG) >= AA_NORMAL
    # --muted is used for secondary/meta text; hold it to the same normal bar.
    assert contrast_ratio(MUTED, PAPER) >= AA_NORMAL
    assert contrast_ratio(MUTED, PAPER_STRONG) >= AA_NORMAL


def test_readiness_status_chip_contrast() -> None:
    """Readiness chips (designed/partial/missing) clear AA for chip text."""
    # designed: --accent-dark on the opaque --accent-soft fill.
    assert contrast_ratio(ACCENT_DARK, ACCENT_SOFT) >= AA_NORMAL
    # partial: --amber-ink on the flattened --amber-soft fill (both surfaces).
    assert contrast_ratio(AMBER_INK, AMBER_SOFT_ON_WHITE) >= AA_NORMAL
    assert contrast_ratio(AMBER_INK, AMBER_SOFT_ON_PAPER) >= AA_NORMAL
    # missing: --danger on the flattened --danger-soft fill (both surfaces).
    assert contrast_ratio(DANGER, DANGER_SOFT_ON_WHITE) >= AA_NORMAL
    assert contrast_ratio(DANGER, DANGER_SOFT_ON_PAPER) >= AA_NORMAL


def test_severity_chip_contrast() -> None:
    """Severity chips (default/medium/high/critical) clear AA for chip text."""
    # default .tag and .sev-low render --accent-dark on --accent-soft.
    assert contrast_ratio(ACCENT_DARK, ACCENT_SOFT) >= AA_NORMAL
    # .sev-medium: --amber-ink on flattened --amber-soft.
    assert contrast_ratio(AMBER_INK, AMBER_SOFT_ON_WHITE) >= AA_NORMAL
    assert contrast_ratio(AMBER_INK, AMBER_SOFT_ON_PAPER) >= AA_NORMAL
    # .sev-high/.sev-critical: --danger on flattened --danger-soft.
    assert contrast_ratio(DANGER, DANGER_SOFT_ON_WHITE) >= AA_NORMAL
    assert contrast_ratio(DANGER, DANGER_SOFT_ON_PAPER) >= AA_NORMAL


def test_raw_amber_on_soft_would_fail_so_the_token_split_is_load_bearing() -> None:
    """Regression guard: the raw --amber on --amber-soft is below AA.

    This is *why* --amber-ink exists. If someone reverts the chip text back to
    --amber, the chip tests above flip red — this test documents the failing
    baseline so the split isn't 'simplified' away.
    """
    assert contrast_ratio(AMBER, AMBER_SOFT_ON_WHITE) < AA_NORMAL
    assert contrast_ratio(AMBER, AMBER_SOFT_ON_PAPER) < AA_NORMAL


def test_chip_text_colors_match_the_audited_tokens() -> None:
    """The CSS chip rules really use the tokens this test computed against.

    Without this link, the contrast math could drift away from the shipped CSS.
    Assert each chip rule pairs the expected --*-soft background with the
    expected (accessible) text token.
    """
    css = SHELL_CSS.read_text()

    def _rule_body(selector: str) -> str:
        match = re.search(rf"{re.escape(selector)}\s*{{([^}}]*)}}", css)
        assert match, f"selector {selector} not found in shell.css"
        return match.group(1)

    partial = _rule_body(".tag.readiness-partial")
    assert "var(--amber-soft)" in partial and "var(--amber-ink)" in partial

    medium = _rule_body(".tag.sev-medium")
    assert "var(--amber-soft)" in medium and "var(--amber-ink)" in medium

    designed = _rule_body(".tag.readiness-designed")
    assert "var(--accent-soft)" in designed and "var(--accent-dark)" in designed

    missing = _rule_body(".tag.readiness-missing")
    assert "var(--danger-soft)" in missing and "var(--danger)" in missing

    # The token definitions themselves match the literals audited above.
    assert "--amber-ink: #8a5414;" in css
    assert "--amber: #b5762b;" in css
    assert "--danger: #7d3f36;" in css
    assert "--accent-dark: #213f2f;" in css
    assert "--accent-soft: #dbe8dc;" in css
    assert "--amber-soft: rgba(181, 118, 43, 0.14);" in css


# ---------------------------------------------------------------------------
# CSS-level a11y affordances (assert once against the stylesheet).
# ---------------------------------------------------------------------------


def test_css_declares_reduced_motion_and_focus_visible() -> None:
    css = SHELL_CSS.read_text()
    assert "@media (prefers-reduced-motion: reduce)" in css, (
        "shell.css must honor prefers-reduced-motion"
    )
    assert ":focus-visible" in css, "shell.css must provide a :focus-visible style"


def test_templates_carry_no_inline_raw_color_styles() -> None:
    """Light check: no template uses an inline style= with a raw color.

    Color must flow through tokens in shell.css, never inline hex/rgb in markup.
    """
    templates_dir = SHELL_CSS.parent.parent / "templates"
    color_pattern = re.compile(r"style\s*=\s*\"[^\"]*(#[0-9a-fA-F]{3,6}|rgb\()", re.IGNORECASE)
    offenders: list[str] = []
    for template in sorted(templates_dir.glob("*.html")):
        if color_pattern.search(template.read_text()):
            offenders.append(template.name)
    assert not offenders, f"templates with inline raw-color styles: {offenders}"
