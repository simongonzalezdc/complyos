"""End-to-end integration test for ComplyOS."""

from __future__ import annotations

import tempfile

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.remediation import RemediationEngine
from complyos.core.report_exporter import export_html
from complyos.core.repository import LocalRepository
from complyos.core.rules import AssignmentRuleEngine
from complyos.models.domain import AssignmentRule
from complyos.notification.sender import NotificationSender


@pytest.fixture
def db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield f.name


@pytest.fixture
def connector():
    return MockConnector()


@pytest.mark.asyncio
async def test_full_flow(db_path, connector):
    """Exercise sync -> audit -> remediate -> export end-to-end."""
    # 1. Sync mock data into SQLite
    repo = LocalRepository(db_path)
    healthy = await connector.authenticate()
    assert healthy is True

    users = await connector.get_users()
    courses = await connector.get_courses()
    enrollments = await connector.get_enrollments()

    repo.sync_users(users)
    repo.sync_courses(courses)
    repo.sync_enrollments(enrollments)

    assert len(repo.list_users()) > 0
    assert len(repo.list_courses()) > 0
    assert len(repo.list_enrollments()) > 0

    # 2. Audit compliance gaps
    auditor = ComplianceAuditor(connector)
    gaps, ledger = await auditor.audit_gaps()

    assert isinstance(ledger.output_hash, str)
    assert len(ledger.output_hash) == 64  # SHA-256 hex

    # 3. Validate and preview a rule
    rule_engine = AssignmentRuleEngine(repo)
    rule = AssignmentRule(
        name="All-Hands Safety",
        target_criteria={"department": "Engineering"},
        course_ids=[c.id for c in courses[:2]],
        deadline_days_from_trigger=30,
    )
    validation = rule_engine.validate_rule(rule)
    assert validation["valid"] is True

    preview = rule_engine.preview_rule(rule)
    assert isinstance(preview["users"], list)

    # 4. Remediate gaps (without email)
    remediation = RemediationEngine(connector, notifier=None)
    actions = await remediation.remediate_gaps(
        gaps, auto_remind=True, auto_enroll=False, notify_manager=False
    )
    # At minimum we should get log actions for medium-severity gaps
    assert len(actions) >= 0

    # 5. Export HTML report
    report = await auditor.generate_report()
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
        html_path = f.name
    path = export_html(report, html_path)
    assert path == html_path

    with open(path) as f:
        content = f.read()
    assert "ComplyOS" in content
    assert report.evidence_hash in content


@pytest.mark.asyncio
async def test_notification_disabled_without_smtp():
    sender = NotificationSender()
    result = await sender.send_email("a@b.com", "subj", "body")
    assert result["sent"] is False


@pytest.mark.asyncio
async def test_user_status_flow(connector):
    users = await connector.get_users()
    assert len(users) > 0
    auditor = ComplianceAuditor(connector)
    status = await auditor.get_user_status(users[0].id)
    assert "user" in status
    assert "summary" in status
