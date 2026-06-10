"""Unit tests for the HTML dashboard generator."""

from __future__ import annotations

from datetime import datetime

from complyos.core.dashboard import generate_dashboard
from complyos.models.domain import AuditReport, ComplianceGap, Course, User


def make_user(uid: str = "u1", name: str = "Alice", dept: str = "Engineering") -> User:
    return User(
        id=uid, employee_id=f"E-{uid}", email=f"{name.lower()}@example.com",
        first_name=name, last_name="Smith", department=dept, region="US",
        hire_date=datetime.now().date(),
    )


def make_report(gaps: list[ComplianceGap] | None = None) -> AuditReport:
    gaps = gaps if gaps is not None else [
        ComplianceGap(
            user=make_user(),
            missing_courses=[Course(id="c1", code="SEC-101", title="Security", mandatory=True)],
            severity="critical",
            days_overdue=45,
        )
    ]
    return AuditReport(
        generated_at=datetime(2026, 6, 10, 12, 0),
        scope="all",
        total_users_audited=len({g.user.id for g in gaps}),
        gaps_found=len(gaps),
        gaps_by_severity={"critical": 1, "high": 0, "medium": 0, "low": 0},
        gaps_by_department={"Engineering": 1},
        top_missing_courses=[("Security", 1)],
        evidence_hash="abc123",
        details=gaps,
    )


def snapshot(gaps_found: int, when: datetime) -> dict:
    return {
        "id": "s", "generated_at": when, "scope": "all",
        "gaps_found": gaps_found, "gaps": [], "gaps_by_severity": {},
        "evidence_hash": "h",
    }


class TestDashboard:
    def test_writes_file_with_report_data(self, tmp_path):
        out = tmp_path / "dash.html"
        path = generate_dashboard(make_report(), output_path=str(out))
        content = out.read_text()
        assert path == str(out)
        assert "Alice Smith" in content
        assert "Security" in content
        assert "badge-critical" in content
        assert "abc123" in content

    def test_accessibility_landmarks_present(self, tmp_path):
        out = tmp_path / "dash.html"
        generate_dashboard(make_report(), output_path=str(out))
        content = out.read_text()
        assert 'class="skip-link"' in content
        assert "<main>" in content
        assert "prefers-reduced-motion" in content
        assert ":focus-visible" in content

    def test_no_history_shows_empty_trend(self, tmp_path):
        out = tmp_path / "dash.html"
        generate_dashboard(make_report(), history=[], output_path=str(out))
        content = out.read_text()
        assert "Not enough history" in content
        assert "<polyline" not in content

    def test_history_renders_trend_svg(self, tmp_path):
        out = tmp_path / "dash.html"
        history = [
            snapshot(5, datetime(2026, 6, 9)),
            snapshot(8, datetime(2026, 6, 2)),
        ]
        generate_dashboard(make_report(), history=history, output_path=str(out))
        content = out.read_text()
        assert "<polyline" in content
        assert 'role="img"' in content
        # newest-first history reversed + current: 8, 5, 1
        assert "8, 5, 1" in content

    def test_trend_counts_course_gaps_not_users(self, tmp_path):
        # One user missing two courses must plot as 2, matching how
        # digest snapshots count flattened (user, course) pairs.
        report = make_report(gaps=[
            ComplianceGap(
                user=make_user(),
                missing_courses=[
                    Course(id="c1", code="SEC-101", title="Security", mandatory=True),
                    Course(id="c2", code="RESPECT-101", title="Respect", mandatory=True),
                ],
                severity="high",
            )
        ])
        out = tmp_path / "dash.html"
        generate_dashboard(report, history=[snapshot(3, datetime(2026, 6, 9))],
                           output_path=str(out))
        assert "3, 2" in out.read_text()

    def test_empty_report_renders_compliant_message(self, tmp_path):
        report = make_report(gaps=[])
        report.gaps_by_department = {}
        out = tmp_path / "dash.html"
        generate_dashboard(report, output_path=str(out))
        content = out.read_text()
        assert "fully compliant" in content
        assert "No gaps in any department" in content

    def test_user_data_is_html_escaped(self, tmp_path):
        evil = make_user(name="Mallory")
        evil.last_name = '<script>alert("x")</script>'
        report = make_report(gaps=[
            ComplianceGap(
                user=evil,
                missing_courses=[Course(id="c1", code="X", title="T & Co", mandatory=True)],
                severity="low",
            )
        ])
        out = tmp_path / "dash.html"
        generate_dashboard(report, output_path=str(out))
        content = out.read_text()
        assert '<script>alert("x")</script>' not in content
        assert "&lt;script&gt;" in content
        assert "T &amp; Co" in content
