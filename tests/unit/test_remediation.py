"""Tests for the RemediationEngine."""

from __future__ import annotations

from datetime import date

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.remediation import RemediationEngine
from complyos.models.domain import ComplianceGap, Course, User


@pytest.fixture
def mock_connector():
    return MockConnector()


@pytest.fixture
def engine(mock_connector: MockConnector):
    return RemediationEngine(mock_connector)


class TestRemediateGaps:
    async def test_critical_gap_sends_reminder_and_manager_notification(
        self, engine: RemediationEngine
    ):
        gap = ComplianceGap(
            user=User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
                manager_id="m1",
            ),
            missing_courses=[Course(id="c1", code="SEC-101", title="Security")],
            severity="critical",
        )
        actions = await engine.remediate_gaps([gap], notify_manager=True)
        assert len(actions) == 2
        assert any(a.action_type == "reminder" for a in actions)
        assert any(a.action_type == "notify_manager" for a in actions)

    async def test_high_gap_sends_reminder(self, engine: RemediationEngine):
        gap = ComplianceGap(
            user=User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
            missing_courses=[Course(id="c1", code="SEC-101", title="Security")],
            severity="high",
        )
        actions = await engine.remediate_gaps([gap])
        assert len(actions) == 1
        assert actions[0].action_type == "reminder"

    async def test_medium_gap_logs_only(self, engine: RemediationEngine):
        gap = ComplianceGap(
            user=User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
            missing_courses=[Course(id="c1", code="SEC-101", title="Security")],
            severity="medium",
        )
        actions = await engine.remediate_gaps([gap])
        assert len(actions) == 1
        assert actions[0].action_type == "log"
        assert actions[0].status == "logged"

    async def test_low_gap_no_action(self, engine: RemediationEngine):
        gap = ComplianceGap(
            user=User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
            missing_courses=[Course(id="c1", code="SEC-101", title="Security")],
            severity="low",
        )
        actions = await engine.remediate_gaps([gap])
        assert len(actions) == 0

    async def test_auto_enroll_adds_enrollment_action(self, engine: RemediationEngine):
        gap = ComplianceGap(
            user=User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
            missing_courses=[Course(id="c1", code="SEC-101", title="Security")],
            severity="high",
        )
        actions = await engine.remediate_gaps([gap], auto_enroll=True)
        assert len(actions) == 2
        assert any(a.action_type == "reminder" for a in actions)
        assert any(a.action_type == "enroll" for a in actions)

    async def test_disabled_auto_remind_skips_high(self, engine: RemediationEngine):
        gap = ComplianceGap(
            user=User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
            missing_courses=[Course(id="c1", code="SEC-101", title="Security")],
            severity="high",
        )
        actions = await engine.remediate_gaps([gap], auto_remind=False)
        assert len(actions) == 0

    async def test_multiple_missing_courses(self, engine: RemediationEngine):
        gap = ComplianceGap(
            user=User(
                id="u1",
                employee_id="E001",
                email="a@example.com",
                first_name="A",
                last_name="A",
                department="Eng",
                region="US",
                hire_date=date(2023, 1, 1),
                employment_status="active",
            ),
            missing_courses=[
                Course(id="c1", code="SEC-101", title="Security"),
                Course(id="c2", code="LEAD-101", title="Leadership"),
            ],
            severity="high",
        )
        actions = await engine.remediate_gaps([gap])
        assert len(actions) == 2
        assert all(a.action_type == "reminder" for a in actions)
