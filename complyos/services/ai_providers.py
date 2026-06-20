"""Pluggable content providers for the proposal-only AI layer.

``AIProposalService`` keeps ownership of the security-critical work: PII
redaction (always runs first), hashing/provenance, persistence, and the
approve/reject/expiry lifecycle. A *provider* is responsible only for turning an
**already-redacted, PII-free** task payload into the structured content dict the
service stores (the per-task fields, *without* the proposal-only guardrail flags
— the service stamps those).

Two providers ship today:

- :class:`DeterministicProvider` — the original deterministic rules. It is the
  DEFAULT and the fallback. With no AI env configured, behavior is byte-identical
  to the pre-provider implementation.
- :class:`LocalModelProvider` — calls an OpenAI-compatible
  ``POST {base_url}/chat/completions`` endpoint (e.g. Ollama, llama.cpp,
  vLLM, LM Studio) with ``response_format={"type": "json_object"}``. The prompt is
  built ONLY from the redacted payload. The response is parsed and validated
  against a per-task Pydantic schema. On timeout / HTTP error / invalid JSON /
  schema mismatch it raises :class:`ProviderUnavailableError`, and the service
  falls back to the deterministic provider for that task.

A provider NEVER sees raw PII: the service redacts before calling it, and every
provider method receives only the redacted projection. Providers also never
mutate compliance state — they return content, nothing else.
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from complyos.connectors.normalization import ENROLLMENT_ALIASES
from complyos.connectors.normalization import normalize_header as _normalize_header

DETERMINISTIC_PROVIDER_ID = "deterministic-local"
LOCAL_MODEL_PROVIDER_ID = "local-openai-compatible"

DEFAULT_LOCAL_MODEL = "llama3.1:8b"
DEFAULT_LOCAL_TIMEOUT_SECONDS = 30.0


def _norm(value: Any) -> str:
    """Normalize a value into a stable lowercase match key (for clustering)."""
    return "" if value is None else " ".join(str(value).split()).strip().lower()


class ProviderUnavailableError(RuntimeError):
    """Raised when a provider cannot produce a valid result for a task.

    The service catches this and falls back to the deterministic provider so a
    model outage can never raise to the caller or block a proposal.
    """

    def __init__(self, provider_id: str, task: str, reason: str) -> None:
        super().__init__(f"{provider_id} unavailable for {task}: {reason}")
        self.provider_id = provider_id
        self.task = task
        self.reason = reason
        self.code = "ai_provider_unavailable"


@runtime_checkable
class ProposalProvider(Protocol):
    """Content generator for the five proposal-only AI tasks.

    Every method receives an already-redacted, PII-free payload and returns the
    structured content dict for that task (per-task fields only; the service adds
    the proposal-only guardrail flags and provenance).
    """

    provider_id: str

    def suggest_mappings(self, headers: list[str], target_schema: str) -> dict[str, Any]:
        ...

    def anomaly_summary(self, issue_codes: list[str]) -> dict[str, Any]:
        ...

    def gap_explanation(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def remediation_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def duplicate_clustering(
        self, redacted_rows: list[dict[str, Any]], rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        ...


# ---------------------------------------------------------------------------
# Deterministic provider (the original logic, the default + the fallback)
# ---------------------------------------------------------------------------
class DeterministicProvider:
    """The original deterministic rules, refactored behind the provider seam."""

    provider_id = DETERMINISTIC_PROVIDER_ID

    def suggest_mappings(self, headers: list[str], target_schema: str) -> dict[str, Any]:
        aliases = {
            candidate: canonical
            for canonical, candidates in ENROLLMENT_ALIASES.items()
            for candidate in [_normalize_header(canonical), *candidates]
        }
        suggestions: dict[str, str | None] = {
            header: aliases.get(_normalize_header(header)) for header in headers
        }
        return {
            "target_schema": target_schema,
            "suggested_mappings": suggestions,
        }

    def anomaly_summary(self, issue_codes: list[str]) -> dict[str, Any]:
        codes = sorted(issue_codes)
        counts: dict[str, int] = {}
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
        total = len(codes)
        parts = [f"{count} {code}" for code, count in sorted(counts.items())]
        summary = (
            f"{total} anomaly signal(s): " + ", ".join(parts)
            if total
            else "no anomaly signals detected"
        )
        return {
            "summary": summary,
            "counts_by_code": counts,
            "total_signals": total,
        }

    def gap_explanation(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload["user_id"])
        department = payload.get("department")
        titles = list(payload.get("missing_courses") or [])
        days_overdue = payload.get("days_overdue")
        severity = str(payload.get("severity", "medium"))
        course_clause = ", ".join(titles) if titles else "no outstanding courses"
        overdue_clause = (
            f" Overdue by {int(days_overdue)} day(s)." if days_overdue else " Not yet overdue."
        )
        explanation = (
            f"Learner {user_id} in {department or 'an unspecified department'} has "
            f"{len(titles)} outstanding mandatory course(s): {course_clause}."
            f"{overdue_clause} Severity: {severity}."
        )
        return {
            "user_id": user_id,
            "department": department,
            "missing_courses": titles,
            "days_overdue": days_overdue,
            "severity": severity,
            "explanation": explanation,
        }

    def remediation_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        user_id = str(payload["user_id"])
        titles = list(payload.get("missing_courses") or [])
        deadline = payload.get("deadline")
        course_clause = (
            ", ".join(titles) if titles else "your assigned mandatory training"
        )
        deadline_clause = (
            f" Please complete by {deadline}." if deadline else " Please complete it promptly."
        )
        message = (
            f"Reminder for learner {user_id}: you have {len(titles)} outstanding "
            f"mandatory course(s): {course_clause}.{deadline_clause}"
        )
        return {
            "user_id": user_id,
            "missing_courses": titles,
            "deadline": deadline,
            "message_draft": message,
        }

    def duplicate_clustering(
        self, redacted_rows: list[dict[str, Any]], rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        from complyos.services.ai_proposals import _hash  # local: avoid import cycle

        clusters: dict[str, list[int]] = {}
        for index, row in enumerate(rows):
            emp = _norm(row.get("employee_id") or row.get("emp_id"))
            name = _norm(
                row.get("name")
                or f"{row.get('first_name', '')} {row.get('last_name', '')}"
            )
            course = _norm(row.get("course_id") or row.get("course"))
            identity = emp or (f"{name}|{course}" if name.strip() else "")
            if not identity.strip("|"):
                continue
            signature = _hash({"identity": identity})
            clusters.setdefault(signature, []).append(index)
        duplicate_clusters = [
            {"signature": signature[:16], "row_numbers": indexes, "size": len(indexes)}
            for signature, indexes in clusters.items()
            if len(indexes) > 1
        ]
        return {
            "duplicate_clusters": duplicate_clusters,
            "rows_examined": len(rows),
            "duplicate_groups": len(duplicate_clusters),
        }


# ---------------------------------------------------------------------------
# Per-task response schemas (validate the model's JSON; mismatch => unavailable)
# ---------------------------------------------------------------------------
class _MappingSchema(BaseModel):
    suggested_mappings: dict[str, str | None]


class _AnomalySchema(BaseModel):
    summary: str


class _GapSchema(BaseModel):
    explanation: str


class _RemediationSchema(BaseModel):
    message_draft: str


class _DuplicateClustersSchema(BaseModel):
    duplicate_clusters: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# Local-model provider (OpenAI-compatible chat/completions)
# ---------------------------------------------------------------------------
class LocalModelProvider:
    """Calls an OpenAI-compatible local inference endpoint for proposal content.

    The endpoint is expected to honor ``response_format={"type": "json_object"}``
    (Ollama, llama.cpp server, vLLM, LM Studio all do). The prompt is constructed
    ONLY from the already-redacted payload. Any failure mode — timeout, non-2xx,
    non-JSON body, or schema mismatch — raises :class:`ProviderUnavailableError`
    so the service can fall back deterministically.
    """

    provider_id = LOCAL_MODEL_PROVIDER_ID

    def __init__(
        self,
        base_url: str,
        model: str = DEFAULT_LOCAL_MODEL,
        *,
        timeout: float = DEFAULT_LOCAL_TIMEOUT_SECONDS,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key
        self._client = client

    @property
    def endpoint_host(self) -> str:
        """Host[:port] of the endpoint — the only URL fragment fit for provenance."""
        return urlparse(self.base_url).netloc or self.base_url

    # -- task methods -------------------------------------------------------
    def suggest_mappings(self, headers: list[str], target_schema: str) -> dict[str, Any]:
        system = (
            "You map spreadsheet column headers to a fixed compliance schema. "
            "Return strict JSON: {\"suggested_mappings\": {<header>: <field-or-null>}}. "
            "Use null when no field fits. Output JSON only."
        )
        user = json.dumps({"target_schema": target_schema, "headers": headers})
        data = self._complete("field_mapping", system, user, _MappingSchema)
        return {
            "target_schema": target_schema,
            "suggested_mappings": data["suggested_mappings"],
        }

    def anomaly_summary(self, issue_codes: list[str]) -> dict[str, Any]:
        codes = sorted(issue_codes)
        counts: dict[str, int] = {}
        for code in codes:
            counts[code] = counts.get(code, 0) + 1
        system = (
            "Summarize compliance anomaly signal codes in one sentence. "
            "Return strict JSON: {\"summary\": <string>}. Output JSON only."
        )
        user = json.dumps({"issue_codes": codes, "counts_by_code": counts})
        data = self._complete("anomaly_summary", system, user, _AnomalySchema)
        return {
            "summary": data["summary"],
            "counts_by_code": counts,
            "total_signals": len(codes),
        }

    def gap_explanation(self, payload: dict[str, Any]) -> dict[str, Any]:
        system = (
            "Draft a plain-language explanation of one compliance gap. "
            "Address the learner only by the opaque user_id; never invent a name "
            "or email. Return strict JSON: {\"explanation\": <string>}. JSON only."
        )
        user = json.dumps(payload)
        data = self._complete("gap_explanation", system, user, _GapSchema)
        return {
            "user_id": str(payload["user_id"]),
            "department": payload.get("department"),
            "missing_courses": list(payload.get("missing_courses") or []),
            "days_overdue": payload.get("days_overdue"),
            "severity": str(payload.get("severity", "medium")),
            "explanation": data["explanation"],
        }

    def remediation_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        system = (
            "Draft a short reminder message for outstanding mandatory training. "
            "Address the learner only by the opaque user_id; never invent a name "
            "or email. Return strict JSON: {\"message_draft\": <string>}. JSON only."
        )
        user = json.dumps(payload)
        data = self._complete("remediation_message", system, user, _RemediationSchema)
        return {
            "user_id": str(payload["user_id"]),
            "missing_courses": list(payload.get("missing_courses") or []),
            "deadline": payload.get("deadline"),
            "message_draft": data["message_draft"],
        }

    def duplicate_clustering(
        self, redacted_rows: list[dict[str, Any]], rows: list[dict[str, Any]]
    ) -> dict[str, Any]:
        system = (
            "Cluster likely-duplicate rows by index. The input rows are already "
            "PII-redacted. Return strict JSON: {\"duplicate_clusters\": "
            "[{\"row_numbers\": [<int>...], \"size\": <int>}...]}. JSON only."
        )
        user = json.dumps({"redacted_rows": redacted_rows})
        data = self._complete("duplicate_clustering", system, user, _DuplicateClustersSchema)
        clusters = [c for c in data["duplicate_clusters"] if len(c.get("row_numbers", [])) > 1]
        normalized = [
            {
                "signature": str(cluster.get("signature", ""))[:16],
                "row_numbers": [int(n) for n in cluster["row_numbers"]],
                "size": len(cluster["row_numbers"]),
            }
            for cluster in clusters
        ]
        return {
            "duplicate_clusters": normalized,
            "rows_examined": len(rows),
            "duplicate_groups": len(normalized),
        }

    # -- transport ----------------------------------------------------------
    def _complete(
        self,
        task: str,
        system_prompt: str,
        user_prompt: str,
        schema: type[BaseModel],
    ) -> dict[str, Any]:
        """POST to the OpenAI-compatible endpoint and validate the JSON reply.

        Raises ProviderUnavailableError on any failure so the service falls back.
        """
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self._request(body, headers)
            response.raise_for_status()
            envelope = response.json()
            content = envelope["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
            validated = schema.model_validate(parsed)
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(self.provider_id, task, f"timeout: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            raise ProviderUnavailableError(
                self.provider_id, task, f"http {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError(self.provider_id, task, f"transport: {exc}") from exc
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderUnavailableError(
                self.provider_id, task, f"invalid response: {exc}"
            ) from exc
        except ValidationError as exc:
            raise ProviderUnavailableError(
                self.provider_id, task, f"schema mismatch: {exc.error_count()} error(s)"
            ) from exc
        return validated.model_dump()

    def _request(self, body: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        if self._client is not None:
            return self._client.post(
                "/chat/completions", json=body, headers=headers, timeout=self.timeout
            )
        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            return client.post("/chat/completions", json=body, headers=headers)


def provider_from_env() -> ProposalProvider:
    """Select the configured provider from the environment.

    Default (``COMPLYOS_AI_PROVIDER`` unset or ``deterministic``) returns the
    :class:`DeterministicProvider`, so with no env set behavior is byte-identical
    to the pre-provider implementation. ``local`` / ``local-openai-compatible``
    builds a :class:`LocalModelProvider` from ``COMPLYOS_AI_BASE_URL`` (required),
    ``COMPLYOS_AI_MODEL``, ``COMPLYOS_AI_TIMEOUT_SECONDS``, ``COMPLYOS_AI_API_KEY``.
    A misconfigured local provider (no base URL) silently uses the deterministic
    provider rather than failing the caller.
    """
    choice = (os.getenv("COMPLYOS_AI_PROVIDER") or "deterministic").strip().lower()
    if choice in ("local", "local-openai-compatible", "openai-compatible"):
        base_url = os.getenv("COMPLYOS_AI_BASE_URL")
        if not base_url:
            return DeterministicProvider()
        return LocalModelProvider(
            base_url=base_url,
            model=os.getenv("COMPLYOS_AI_MODEL") or DEFAULT_LOCAL_MODEL,
            timeout=_timeout_from_env(),
            api_key=os.getenv("COMPLYOS_AI_API_KEY"),
        )
    return DeterministicProvider()


def _timeout_from_env() -> float:
    raw = os.getenv("COMPLYOS_AI_TIMEOUT_SECONDS")
    if not raw:
        return DEFAULT_LOCAL_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_LOCAL_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_LOCAL_TIMEOUT_SECONDS
