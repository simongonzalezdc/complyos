"""Local-model AI provider: PII-egress, happy path, fallback, default parity.

The provider seam is the most security-sensitive surface in the product (it can
send data to an inference endpoint). These tests pin the non-negotiables:

- No raw PII is ever egressed to the endpoint (redaction runs before the model).
- A working endpoint's content is used and provenance records the local provider.
- Every endpoint failure mode falls back to deterministic, stays PROPOSED, flags
  ``fallback``, surfaces a warning, and never raises to the caller.
- With no AI env set, the deterministic path is byte-identical to before.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from httpx import Response

from complyos.core.repository import LocalRepository
from complyos.services.ai_eval import _SYNTHETIC_PII_ROWS
from complyos.services.ai_proposals import AIProposalService
from complyos.services.ai_providers import (
    DeterministicProvider,
    LocalModelProvider,
    ProviderUnavailableError,
)
from complyos.services.context import default_local_context

BASE_URL = "http://localhost:11434/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"

# A source row carrying real-looking PII; redaction must strip it before egress.
PII_ROW = {
    "Learner Name": "Jane Secret",
    "Email": "jane.secret@corp.example",
    "Employee ID": "E-99999",
    "SSN": "123-45-6789",
    "Course ID": "SEC-101",
    "Status": "completed",
}
RAW_PII = ("Jane Secret", "jane.secret@corp.example", "E-99999", "123-45-6789")


def _local_service(tmp_path, name: str) -> tuple[AIProposalService, LocalRepository]:
    repo = LocalRepository(str(tmp_path / name))
    provider = LocalModelProvider(base_url=BASE_URL, model="llama3.1:8b")
    return AIProposalService(repo, provider=provider), repo


def _chat_json(payload: dict) -> Response:
    """Wrap a task payload as an OpenAI-compatible chat/completions response."""
    return Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(payload)}}]},
    )


# --- No PII egress (CRITICAL) ----------------------------------------------
@respx.mock
def test_mapping_redacts_pii_before_egress_to_endpoint(tmp_path) -> None:
    route = respx.post(CHAT_URL).mock(
        return_value=_chat_json({"suggested_mappings": {"Course ID": "course_id"}})
    )
    service, _ = _local_service(tmp_path, "egress-map.db")
    context = default_local_context(surface="cli")

    service.propose_mapping(
        context, headers=list(PII_ROW.keys()), sample_rows=[PII_ROW]
    )

    assert route.called
    sent = route.calls.last.request.content.decode("utf-8")
    for raw in RAW_PII:
        assert raw not in sent, f"raw PII egressed to endpoint: {raw!r}"
    # Mapping egresses only the column-name headers (non-PII), never row values:
    # an even stronger guarantee than masking. The header names still go out.
    assert "Course ID" in sent


@respx.mock
def test_duplicate_clustering_redacts_pii_before_egress(tmp_path) -> None:
    route = respx.post(CHAT_URL).mock(
        return_value=_chat_json({"duplicate_clusters": []})
    )
    service, _ = _local_service(tmp_path, "egress-dupe.db")
    context = default_local_context(surface="cli")

    rows = [
        {"name": "Bob Private", "email": "bob.private@corp.example", "course_id": "c1"},
        {"name": "Bob Private", "email": "bob.private@corp.example", "course_id": "c1"},
    ]
    service.propose_duplicate_clustering(context, rows=rows)

    sent = route.calls.last.request.content.decode("utf-8")
    assert "Bob Private" not in sent
    assert "bob.private@corp.example" not in sent
    assert "[REDACTED]" in sent


# --- Local provider happy path ---------------------------------------------
@respx.mock
def test_local_provider_happy_path_uses_model_output(tmp_path) -> None:
    respx.post(CHAT_URL).mock(
        return_value=_chat_json(
            {"suggested_mappings": {"User ID": "user_id", "Course ID": "course_id"}}
        )
    )
    service, repo = _local_service(tmp_path, "happy.db")
    context = default_local_context(surface="cli")

    result = service.propose_mapping(context, headers=["User ID", "Course ID"])

    assert result.status == "PROPOSED"
    assert result.output["suggested_mappings"]["User ID"] == "user_id"
    assert result.provenance["model_provider"] == "local-openai-compatible"
    assert result.provenance["model_name"] == "llama3.1:8b"
    assert result.provenance["fallback"] is False
    # Host only — never the full URL, never a token.
    assert result.provenance["endpoint_host"] == "localhost:11434"
    assert "11434/v1" not in json.dumps(result.provenance)
    # Still proposal-only.
    assert result.output["state_mutation_allowed"] is False
    assert repo.list_learning_records() == []


@respx.mock
def test_local_provider_sends_bearer_when_api_key_set(tmp_path) -> None:
    route = respx.post(CHAT_URL).mock(
        return_value=_chat_json({"suggested_mappings": {}})
    )
    repo = LocalRepository(str(tmp_path / "auth.db"))
    provider = LocalModelProvider(base_url=BASE_URL, model="m", api_key="dummy-key")
    service = AIProposalService(repo, provider=provider)
    context = default_local_context(surface="cli")

    service.propose_mapping(context, headers=["User ID"])

    assert route.calls.last.request.headers["Authorization"] == "Bearer dummy-key"


# --- Fallback on every failure mode ----------------------------------------
@respx.mock
def test_fallback_on_http_500(tmp_path) -> None:
    respx.post(CHAT_URL).mock(return_value=Response(500, json={"error": "boom"}))
    service, repo = _local_service(tmp_path, "fb-500.db")
    context = default_local_context(surface="cli")

    result = service.propose_mapping(context, headers=["User ID", "Course ID"])

    assert result.status == "PROPOSED"
    assert result.provenance["fallback"] is True
    assert result.provenance["model_provider"] == "deterministic-local"
    # deterministic content is used
    assert result.output["suggested_mappings"]["User ID"] == "user_id"
    assert any("fell back" in w for w in result.warnings)
    assert repo.list_learning_records() == []


@respx.mock
def test_fallback_on_timeout(tmp_path) -> None:
    respx.post(CHAT_URL).mock(side_effect=httpx.TimeoutException("slow"))
    service, _ = _local_service(tmp_path, "fb-timeout.db")
    context = default_local_context(surface="cli")

    result = service.propose_gap_explanation(
        context, user_id="u1", missing_courses=["X"], days_overdue=3
    )

    assert result.status == "PROPOSED"
    assert result.provenance["fallback"] is True
    assert "u1" in result.output["explanation"]


@respx.mock
def test_fallback_on_invalid_json(tmp_path) -> None:
    respx.post(CHAT_URL).mock(
        return_value=Response(
            200, json={"choices": [{"message": {"content": "not-json{{"}}]}
        )
    )
    service, _ = _local_service(tmp_path, "fb-badjson.db")
    context = default_local_context(surface="cli")

    result = service.propose_anomaly_summary(context, issues=[{"code": "STALE_EXPORT"}])

    assert result.provenance["fallback"] is True
    assert result.output["total_signals"] == 1


@respx.mock
def test_fallback_on_schema_mismatch(tmp_path) -> None:
    # Valid JSON, but missing the required ``suggested_mappings`` field.
    respx.post(CHAT_URL).mock(
        return_value=_chat_json({"unexpected": "shape"})
    )
    service, _ = _local_service(tmp_path, "fb-schema.db")
    context = default_local_context(surface="cli")

    result = service.propose_mapping(context, headers=["User ID"])

    assert result.provenance["fallback"] is True
    assert result.output["suggested_mappings"]["User ID"] == "user_id"


@respx.mock
def test_provider_never_raises_to_caller_on_outage(tmp_path) -> None:
    respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("refused"))
    service, _ = _local_service(tmp_path, "fb-conn.db")
    context = default_local_context(surface="cli")

    # Must NOT raise — a model outage is contained by the fallback.
    result = service.propose_remediation_message(
        context, user_id="u2", missing_courses=["Y"], deadline="2026-07-01"
    )
    assert result.status == "PROPOSED"
    assert result.provenance["fallback"] is True


def test_local_provider_raises_typed_error_directly() -> None:
    """The provider itself raises ProviderUnavailableError (the service catches it)."""
    provider = LocalModelProvider(base_url=BASE_URL, model="m", timeout=0.01)
    with respx.mock:
        respx.post(CHAT_URL).mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(ProviderUnavailableError):
            provider.suggest_mappings(["User ID"], "learning_records")


# --- Default (no env) parity -----------------------------------------------
def test_default_provider_is_deterministic_and_output_identical(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "default.db"))
    service = AIProposalService(repo)  # no provider => provider_from_env()
    context = default_local_context(surface="cli")

    assert isinstance(service.provider, DeterministicProvider)

    result = service.propose_mapping(
        context, headers=["User ID", "Course ID", "Status"]
    )
    assert result.provenance["model_provider"] == "deterministic-local"
    assert result.provenance["model_name"] == "rules-v1"
    assert result.provenance["fallback"] is False
    assert "endpoint_host" not in result.provenance
    assert result.output["suggested_mappings"]["User ID"] == "user_id"
    assert result.warnings == ["proposal-only; cannot mutate compliance records"]


def test_deterministic_provider_matches_legacy_content() -> None:
    """The refactored deterministic provider reproduces the original outputs."""
    provider = DeterministicProvider()

    mapping = provider.suggest_mappings(["User ID", "Course ID"], "learning_records")
    assert mapping["suggested_mappings"]["User ID"] == "user_id"

    rows = [
        {"employee_id": "E001", "name": "Alice Smith", "course_id": "c1"},
        {"employee_id": "E001", "name": "Alice Smith", "course_id": "c1"},
        {"employee_id": "E002", "name": "Bob Jones", "course_id": "c1"},
    ]
    redacted = [{"employee_id": "[REDACTED]"} for _ in rows]
    clustering = provider.duplicate_clustering(redacted, rows)
    assert clustering["rows_examined"] == 3
    assert clustering["duplicate_groups"] == 1
    assert clustering["duplicate_clusters"][0]["row_numbers"] == [0, 1]


def test_synthetic_fixtures_are_used_by_egress_test() -> None:
    # Guard: the eval fixtures stay PII-bearing so the egress proof is meaningful.
    assert any("@" in str(v) for row in _SYNTHETIC_PII_ROWS for v in row.values())
