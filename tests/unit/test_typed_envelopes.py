"""Typed-envelope regression tests.

WP19 scope-bounded hardening: the legal-hold result, retention-policy result,
and privacy posture result now expose typed models (`LegalHoldResult.scope`
as `LegalHoldScope`, `RetentionPolicyResult.policy` as `RetentionPolicy`,
`PrivacyPostureResult.active_legal_holds` as `list[LegalHoldResult]`) so the
type system catches a typo'd scope or an unknown retention dataset name at
the boundary instead of silently never expiring anything.
"""

from __future__ import annotations

import pytest

from complyos.core.repository import LocalRepository
from complyos.models.domain import (
    LegalHoldScope,
    LegalHoldStatus,
    RetentionPolicy,
)
from complyos.services.context import default_local_context
from complyos.services.privacy import (
    LegalHoldResult,
    PrivacyPostureResult,
    PrivacyProgramService,
    RetentionCleanupResult,
    RetentionPolicyResult,
)


def test_retention_policy_typed_envelope_round_trip() -> None:
    """Stored ``{name: days}`` round-trips through the typed model and back."""
    stored = {
        "privacy_request_days": 90,
        "raw_import_days": 7,
        "ai_proposal_days": 60,
        "evidence_days": 365,
        "action_log_days": 365,
    }
    policy = RetentionPolicy.from_mapping(stored)
    assert policy.privacy_request_days == 90
    assert policy.raw_import_days == 7
    assert policy.ai_proposal_days == 60
    assert policy.evidence_days == 365
    assert policy.action_log_days == 365
    # as_mapping preserves the storage shape and the values are int-typed.
    assert policy.as_mapping() == stored
    assert all(isinstance(v, int) for v in policy.as_mapping().values())


def test_retention_policy_unknown_keys_are_dropped() -> None:
    """A stored policy from an older schema still loads; unknown keys are dropped."""
    legacy = {"raw_import_days": 14, "future_dataset_days": 999}
    policy = RetentionPolicy.from_mapping(legacy)
    assert policy.raw_import_days == 14
    # Missing windows take the documented default.
    assert policy.privacy_request_days == 365
    assert policy.evidence_days == 2555
    # The unknown key never leaks through.
    assert "future_dataset_days" not in policy.as_mapping()


def test_retention_policy_empty_mapping_returns_defaults() -> None:
    """A tenant with no stored policy still produces a complete typed envelope."""
    policy = RetentionPolicy.from_mapping(None)
    assert policy.as_mapping() == {
        "privacy_request_days": 365,
        "raw_import_days": 30,
        "ai_proposal_days": 180,
        "evidence_days": 2555,
        "action_log_days": 2555,
    }


def test_retention_policy_window_for_named_dataset() -> None:
    """``window_for`` is the named-dataset accessor used by the cleanup path."""
    policy = RetentionPolicy(raw_import_days=10, evidence_days=2000)
    assert policy.window_for("raw_import_days") == 10
    assert policy.window_for("evidence_days") == 2000
    with pytest.raises(KeyError, match="unknown retention dataset"):
        policy.window_for("nonsense_dataset")


def test_legal_hold_result_rejects_unknown_scope() -> None:
    """Pydantic v2 catches an out-of-vocabulary scope at construction time."""
    with pytest.raises(ValueError):
        LegalHoldResult(
            hold_id="h1",
            tenant_id="t1",
            subject_id="u1",
            scope="nonsense",  # type: ignore[arg-type]
            reason="r",
            status=LegalHoldStatus.ACTIVE,
        )


def test_legal_hold_result_rejects_unknown_status() -> None:
    with pytest.raises(ValueError):
        LegalHoldResult(
            hold_id="h1",
            tenant_id="t1",
            subject_id="u1",
            scope=LegalHoldScope.SUBJECT,
            reason="r",
            status="NONSENSE",  # type: ignore[arg-type]
        )


def test_privacy_posture_returns_typed_envelopes(tmp_path) -> None:
    """``get_privacy_posture`` exposes typed holds + a typed retention policy."""
    repo = LocalRepository(str(tmp_path / "posture-typed.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    service.create_legal_hold(
        context, subject_id="s1", scope="subject", reason="r1"
    )
    service.configure_retention_policy(
        context,
        raw_import_days=14,
        evidence_days=730,
        action_log_days=730,
        ai_proposal_days=60,
    )
    posture = service.get_privacy_posture(context)
    assert isinstance(posture, PrivacyPostureResult)
    assert posture.active_legal_holds, "expected at least one typed hold"
    for hold in posture.active_legal_holds:
        assert isinstance(hold, LegalHoldResult)
        assert hold.scope in set(LegalHoldScope)
        assert hold.status in set(LegalHoldStatus)
    assert isinstance(posture.retention_policy, RetentionPolicy)
    assert posture.retention_policy.raw_import_days == 14
    assert posture.retention_policy.evidence_days == 730


def test_configure_retention_returns_typed_policy(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "typed-cfg.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    result = service.configure_retention_policy(
        context,
        raw_import_days=5,
        evidence_days=180,
        action_log_days=180,
        ai_proposal_days=30,
    )
    assert isinstance(result, RetentionPolicyResult)
    assert isinstance(result.policy, RetentionPolicy)
    assert result.policy.raw_import_days == 5
    assert result.policy.evidence_days == 180


def test_retention_cleanup_returns_typed_policy(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "typed-cleanup.db"))
    service = PrivacyProgramService(repo)
    context = default_local_context(tenant_id="tenant-a", role="privacy_admin")
    service.configure_retention_policy(
        context,
        raw_import_days=1,
        evidence_days=1,
        action_log_days=1,
        ai_proposal_days=1,
    )
    result = service.run_retention_cleanup(context, dry_run=True)
    assert isinstance(result, RetentionCleanupResult)
    assert isinstance(result.policy, RetentionPolicy)
    assert result.policy.raw_import_days == 1
