"""Eval harness tests: deterministic passes trivially; local model is graded.

The eval proves the harness on the deterministic provider (all five tasks pass)
and, against a mocked local endpoint, grades a model — including catching a
model that leaks PII into its output (the security-critical check).
"""

from __future__ import annotations

import json

import respx
from httpx import Response

from complyos.core.repository import LocalRepository
from complyos.services.ai_eval import run_eval
from complyos.services.ai_proposals import AIProposalService
from complyos.services.ai_providers import LocalModelProvider
from complyos.services.context import default_local_context

BASE_URL = "http://localhost:11434/v1"
CHAT_URL = f"{BASE_URL}/chat/completions"


def test_eval_passes_trivially_with_deterministic_provider(tmp_path) -> None:
    repo = LocalRepository(str(tmp_path / "eval-det.db"))
    service = AIProposalService(repo)
    context = default_local_context(surface="cli")

    report = run_eval(service, context)

    assert report.provider == "deterministic-local"
    assert report.total == 5
    assert report.passed is True
    assert report.passes == 5
    for r in report.results:
        assert r.reachable is True
        assert r.no_pii_leak is True
        assert r.fallback is False


@respx.mock
def test_eval_flags_pii_leak_in_model_output(tmp_path) -> None:
    # A misbehaving model that echoes an email + SSN into its gap explanation.
    def _route(request):
        body = json.loads(request.content)
        messages = body["messages"]
        # Default to a benign mapping reply; poison only the gap task.
        content = {"suggested_mappings": {}}
        for msg in messages:
            if "compliance gap" in msg["content"]:
                content = {
                    "explanation": "Contact evil@leak.example or SSN 123-45-6789 now."
                }
            elif "anomaly signal" in msg["content"]:
                content = {"summary": "ok"}
            elif "reminder message" in msg["content"]:
                content = {"message_draft": "reminder"}
            elif "Cluster" in msg["content"]:
                content = {"duplicate_clusters": []}
        return Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    respx.post(CHAT_URL).mock(side_effect=_route)

    repo = LocalRepository(str(tmp_path / "eval-leak.db"))
    provider = LocalModelProvider(base_url=BASE_URL, model="leaky-model")
    service = AIProposalService(repo, provider=provider)
    context = default_local_context(surface="cli")

    report = run_eval(service, context)

    gap = next(r for r in report.results if r.task == "gap_explanation")
    assert gap.no_pii_leak is False, "eval must catch PII leaking into model output"
    assert gap.passed is False
    assert report.passed is False


@respx.mock
def test_eval_marks_unreachable_when_model_falls_back(tmp_path) -> None:
    respx.post(CHAT_URL).mock(return_value=Response(503, json={"error": "down"}))

    repo = LocalRepository(str(tmp_path / "eval-down.db"))
    provider = LocalModelProvider(base_url=BASE_URL, model="down-model")
    service = AIProposalService(repo, provider=provider)
    context = default_local_context(surface="cli")

    report = run_eval(service, context)

    # Every task fell back to deterministic, so none is "reachable" via the model,
    # but each still produced a valid, PII-free proposal.
    for r in report.results:
        assert r.reachable is False
        assert r.fallback is True
        assert r.valid_json is True
        assert r.no_pii_leak is True
