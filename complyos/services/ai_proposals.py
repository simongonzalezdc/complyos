"""Proposal-only AI assistance with provenance.

This layer can suggest mappings/explanations/drafts. It cannot mark learners
compliant, promote imports, execute remediation, or change assignment rules.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from complyos.connectors.csv_file import ENROLLMENT_ALIASES, _normalize_header
from complyos.core.repository import LocalRepository
from complyos.services.context import (
    PERM_AI_APPROVE,
    PERM_AI_PROPOSE,
    ActorContext,
    require_permission,
)


class AIProposalResult(BaseModel):
    proposal_id: str
    tenant_id: str
    proposal_type: str
    status: str
    input_hash: str
    output_hash: str
    output: dict[str, Any]
    provenance: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class AIProposalService:
    """Stores deterministic/proposal-only AI-style outputs and provenance."""

    def __init__(self, repository: LocalRepository | None = None) -> None:
        self.repository = repository or LocalRepository()

    def propose_mapping(
        self,
        context: ActorContext,
        *,
        headers: list[str],
        target_schema: str = "learning_records",
        model_provider: str = "deterministic-local",
        model_name: str = "rules-v1",
    ) -> AIProposalResult:
        require_permission(context, PERM_AI_PROPOSE)
        payload = {"headers": headers, "target_schema": target_schema}
        input_hash = _hash(payload)
        suggestions = self._suggest_mappings(headers)
        output = {
            "target_schema": target_schema,
            "suggested_mappings": suggestions,
            "state_mutation_allowed": False,
            "requires_human_approval": True,
        }
        output_hash = _hash(output)
        proposal_id = str(uuid4())
        provenance = {
            "model_provider": model_provider,
            "model_name": model_name,
            "prompt_hash": _hash({"task": "field_mapping", "target_schema": target_schema}),
            "redaction_policy": "headers_only_no_records",
            "response_hash": output_hash,
            "created_at": datetime.now(UTC).isoformat(),
        }
        self.repository.save_ai_proposal(
            {
                "id": proposal_id,
                "tenant_id": context.tenant_id,
                "proposal_type": "field_mapping",
                "input_hash": input_hash,
                "output_hash": output_hash,
                "status": "PROPOSED",
                "created_by": context.actor_id,
                "created_at": datetime.now(UTC),
                "output": output,
                "provenance": provenance,
            }
        )
        return AIProposalResult(
            proposal_id=proposal_id,
            tenant_id=context.tenant_id,
            proposal_type="field_mapping",
            status="PROPOSED",
            input_hash=input_hash,
            output_hash=output_hash,
            output=output,
            provenance=provenance,
            warnings=["proposal-only; cannot mutate compliance records"],
        )

    def approve(self, context: ActorContext, proposal_id: str) -> AIProposalResult:
        require_permission(context, PERM_AI_APPROVE)
        proposal = self.repository.get_ai_proposal(proposal_id)
        if proposal is None:
            raise ValueError(f"unknown AI proposal: {proposal_id}")
        if proposal["tenant_id"] != context.tenant_id:
            raise PermissionError("cannot approve proposal for another tenant")
        self.repository.update_ai_proposal_status(
            proposal_id,
            "APPROVED",
            approved_by=context.actor_id,
            approved_at=datetime.now(UTC),
        )
        proposal = self.repository.get_ai_proposal(proposal_id)
        assert proposal is not None
        return AIProposalResult(
            proposal_id=proposal["id"],
            tenant_id=proposal["tenant_id"],
            proposal_type=proposal["proposal_type"],
            status=proposal["status"],
            input_hash=proposal["input_hash"],
            output_hash=proposal["output_hash"],
            output=proposal.get("output") or {},
            provenance=proposal.get("provenance") or {},
            warnings=["approval records review; it still does not mutate compliance truth"],
        )

    @staticmethod
    def _suggest_mappings(headers: list[str]) -> dict[str, str | None]:
        aliases = {
            candidate: canonical
            for canonical, candidates in ENROLLMENT_ALIASES.items()
            for candidate in [_normalize_header(canonical), *candidates]
        }
        return {header: aliases.get(_normalize_header(header)) for header in headers}


def _hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
