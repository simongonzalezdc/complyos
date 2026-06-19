"""AttestationService authorization, evidence, audit-flow, and scoping tests.

AttestationService is the single authorization choke-point for tracking AI-use-
policy / AI-literacy attestations:

- Defining an attestation requirement (a mandatory learning item) makes the
  auditor count an un-attested learner as a ComplianceGap — no parallel engine.
- Recording an attestation is human-recorded evidence: it writes a completed
  LearningRecord AND an evidence-ledger entry atomically. The proposal-only
  agent role CANNOT record one (AI may not mark anyone attested).
- Attestations are tenant-scoped and carry expires_at for annual re-attestation,
  which the existing expiring-soon path picks up.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from complyos.connectors.mock import MockConnector
from complyos.core.auditor import ComplianceAuditor
from complyos.core.expiry_reminder import build_expiring_soon_reminder
from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    AttestationCategory,
    Course,
    EmploymentStatus,
    Enrollment,
    EnrollmentStatus,
    LearningRecordStatus,
    User,
)
from complyos.services.attestations import AttestationService
from complyos.services.context import AuthorizationError, default_local_context

POLICY_VERSION = "ai-use-policy-2026.1"


def _user(user_id: str, *, tenant_id: str = "local-default", email: str | None = None) -> User:
    return User(
        id=user_id,
        employee_id=f"E-{user_id}",
        email=email or f"{user_id}@example.com",
        first_name=user_id.title(),
        last_name="Learner",
        department="Engineering",
        region="US",
        hire_date=date(2023, 1, 1),
        employment_status=EmploymentStatus.ACTIVE,
        custom_attributes={"tenant_id": tenant_id},
    )


def _repo_with_learner(tmp_path, *, tenant_id: str = "local-default") -> LocalRepository:
    repo = LocalRepository(str(tmp_path / "attestations.db"))
    repo.save_user(_user("u1", tenant_id=tenant_id))
    return repo


def _ctx(*, role: str = "compliance_manager", tenant_id: str = "local-default"):
    return default_local_context(surface="cli", role=role, tenant_id=tenant_id)


def _define_requirement(service: AttestationService, context) -> Course:
    return service.define_requirement(
        context,
        course_id="ai-pol",
        code="AI-USE-2026",
        title="AI Use Policy Acknowledgement",
        category=AttestationCategory.AI_USE_POLICY,
    )


# ---------------------------------------------------------------------------
# Defining a requirement produces an audit gap for un-attested learners.
# ---------------------------------------------------------------------------
async def test_defined_requirement_surfaces_unattested_learner_as_gap(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    requirement = _define_requirement(service, _ctx())

    # The auditor reads from a connector. The defined requirement is a mandatory
    # learning item with no completed enrollment for u1 -> a gap.
    connector = MockConnector(seed_data=False)
    connector.users = [_user("u1")]
    connector.courses = [requirement]
    connector.enrollments = []

    gaps, _ledger = await ComplianceAuditor(connector).audit_gaps()

    assert len(gaps) == 1
    assert gaps[0].user.id == "u1"
    assert {c.id for c in gaps[0].missing_courses} == {"ai-pol"}


async def test_recording_attestation_closes_the_gap(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    requirement = _define_requirement(service, _ctx())

    service.record(
        _ctx(),
        user_id="u1",
        requirement_id="ai-pol",
        policy_version=POLICY_VERSION,
    )

    # A connector that reflects the recorded attestation as a completed enrollment
    # for u1 yields no gap (mirrors what a synced LMS/repository would surface).
    connector = MockConnector(seed_data=False)
    connector.users = [_user("u1")]
    connector.courses = [requirement]
    connector.enrollments = [
        Enrollment(
            id="att-1",
            user_id="u1",
            course_id="ai-pol",
            status=EnrollmentStatus.COMPLETED,
            completed_date=datetime.now(),
        )
    ]

    gaps, _ledger = await ComplianceAuditor(connector).audit_gaps()
    assert gaps == []

    # And the readiness record exists, completed/met.
    records = repo.list_learning_records(user_id="u1", course_id="ai-pol")
    assert len(records) == 1
    assert records[0].status == LearningRecordStatus.COMPLETED
    assert records[0].source_system == "attestation"


# ---------------------------------------------------------------------------
# Recording writes an evidence-ledger entry with hash/provenance.
# ---------------------------------------------------------------------------
def test_record_writes_evidence_ledger_entry_with_hash_and_provenance(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    _define_requirement(service, _ctx())

    result = service.record(
        _ctx(),
        user_id="u1",
        requirement_id="ai-pol",
        policy_version=POLICY_VERSION,
    )

    ledger = repo.list_evidence_ledger(tenant_id="local-default")
    entry = next(e for e in ledger if e["id"] == result.evidence_id)
    assert entry["query_type"] == "attestation.record"
    assert entry["query_params"]["user_id"] == "u1"
    assert entry["query_params"]["requirement_id"] == "ai-pol"
    assert entry["output_hash"] == result.output_hash
    assert entry["raw_data_hash"]  # non-empty provenance hash
    assert "recorded_human_attestation" in entry["transformation_steps"]

    # The recording actor and policy version are captured as evidence.
    assert result.recorded_by == "local-compliance_manager"
    assert result.policy_version == POLICY_VERSION
    assert result.category == AttestationCategory.AI_USE_POLICY


def test_record_captures_on_behalf_actor(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    _define_requirement(service, _ctx())

    result = service.record(
        _ctx(),
        user_id="u1",
        requirement_id="ai-pol",
        policy_version=POLICY_VERSION,
        on_behalf=True,
    )
    assert result.recorded_on_behalf is True
    records = repo.list_learning_records(user_id="u1", course_id="ai-pol")
    assert records[0].source_payload["recorded_on_behalf"] is True
    assert records[0].source_payload["policy_version"] == POLICY_VERSION


# ---------------------------------------------------------------------------
# AI / proposal actor CANNOT record an attestation (authz denial).
# ---------------------------------------------------------------------------
def test_agent_service_account_cannot_record_attestation(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    _define_requirement(service, _ctx())

    # The proposal-only MCP default role lacks attestation:record.
    agent_ctx = default_local_context(surface="mcp", role="agent_service_account")

    with pytest.raises(AuthorizationError) as exc:
        service.record(
            agent_ctx,
            user_id="u1",
            requirement_id="ai-pol",
            policy_version=POLICY_VERSION,
        )
    assert exc.value.permission == "attestation:record"

    # No record and no evidence were written by the denied call.
    assert repo.list_learning_records(user_id="u1", course_id="ai-pol") == []


def test_agent_service_account_may_read_but_not_record(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    _define_requirement(service, _ctx())
    service.record(
        _ctx(), user_id="u1", requirement_id="ai-pol", policy_version=POLICY_VERSION
    )

    # The agent role holds attestation:read so it can report un-attested learners.
    agent_ctx = default_local_context(surface="mcp", role="agent_service_account")
    records = service.list_attestations(agent_ctx)
    assert len(records) == 1
    assert records[0].learner_id == "u1"


def test_define_requirement_requires_rules_write(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    # read_only lacks rules:write.
    context = default_local_context(surface="api", role="read_only")
    with pytest.raises(AuthorizationError) as exc:
        _define_requirement(service, context)
    assert exc.value.permission == "rules:write"


def test_list_attestations_requires_attestation_read(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    context = default_local_context(surface="api", role="owner").model_copy(
        update={"permissions": ()}
    )
    with pytest.raises(AuthorizationError) as exc:
        service.list_attestations(context)
    assert exc.value.permission == "attestation:read"


# ---------------------------------------------------------------------------
# Tenant scoping.
# ---------------------------------------------------------------------------
def test_cannot_attest_learner_in_another_tenant(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "scoped.db"))
    repo.save_user(_user("u1", tenant_id="tenant-a"))
    service = AttestationService(repo)
    # Requirement defined under tenant-a (where the learner lives).
    service.define_requirement(
        _ctx(tenant_id="tenant-a"),
        course_id="ai-pol",
        code="AI-USE-2026",
        title="AI Use Policy",
        category=AttestationCategory.AI_USE_POLICY,
    )

    # A context scoped to tenant-b must not be able to attest tenant-a's learner.
    with pytest.raises(PermissionError):
        service.record(
            _ctx(tenant_id="tenant-b"),
            user_id="u1",
            requirement_id="ai-pol",
            policy_version=POLICY_VERSION,
        )


def test_list_attestations_is_tenant_scoped(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "scoped-list.db"))
    repo.save_user(_user("ua", tenant_id="tenant-a"))
    repo.save_user(_user("ub", tenant_id="tenant-b"))
    service = AttestationService(repo)
    for tenant, learner in (("tenant-a", "ua"), ("tenant-b", "ub")):
        service.define_requirement(
            _ctx(tenant_id=tenant),
            course_id=f"ai-pol-{tenant}",
            code=f"AI-{tenant}",
            title="AI Use Policy",
            category=AttestationCategory.AI_USE_POLICY,
        )
        service.record(
            _ctx(tenant_id=tenant),
            user_id=learner,
            requirement_id=f"ai-pol-{tenant}",
            policy_version=POLICY_VERSION,
        )

    records = service.list_attestations(_ctx(tenant_id="tenant-a"))
    assert {r.learner_id for r in records} == {"ua"}


# ---------------------------------------------------------------------------
# Annual re-attestation via expires_at surfaces in the expiring-soon path.
# ---------------------------------------------------------------------------
def test_annual_reattestation_surfaces_in_expiring_soon(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    _define_requirement(service, _ctx())

    as_of = date(2026, 6, 1)
    expires = as_of + timedelta(days=20)  # inside the 30-day window
    service.record(
        _ctx(),
        user_id="u1",
        requirement_id="ai-pol",
        policy_version=POLICY_VERSION,
        expires_at=expires,
    )

    expiring = repo.list_expiring_learning_records(
        tenant_id="local-default",
        as_of=as_of,
        horizon=as_of + timedelta(days=30),
    )
    reminder = build_expiring_soon_reminder(
        tenant_id="local-default",
        records=expiring,
        windows_days=[30, 60, 90],
        as_of=as_of,
    )
    assert reminder.total_expiring == 1
    entry = reminder.groups[0].entries[0]
    assert entry.user_id == "u1"
    assert entry.course_code == "AI-USE-2026"
    assert entry.expires_at == expires


# ---------------------------------------------------------------------------
# Guardrails on bad input.
# ---------------------------------------------------------------------------
def test_record_rejects_non_attestation_requirement(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    repo.save_course(Course(id="c1", code="SEC-101", title="Security", mandatory=True))
    service = AttestationService(repo)
    with pytest.raises(ValueError, match="not an attestation requirement"):
        service.record(
            _ctx(), user_id="u1", requirement_id="c1", policy_version=POLICY_VERSION
        )


def test_record_requires_policy_version(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    _define_requirement(service, _ctx())
    with pytest.raises(ValueError, match="policy_version is required"):
        service.record(_ctx(), user_id="u1", requirement_id="ai-pol", policy_version="  ")


def test_define_requirement_rejects_unknown_category(tmp_path) -> None:
    repo = _repo_with_learner(tmp_path)
    service = AttestationService(repo)
    with pytest.raises(ValueError, match="unknown attestation category"):
        service.define_requirement(
            _ctx(),
            course_id="ai-pol",
            code="AI-USE-2026",
            title="AI Use Policy",
            category="not_a_category",
        )
