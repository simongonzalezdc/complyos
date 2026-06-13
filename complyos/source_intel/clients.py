"""Public/free source clients for source-intelligence snapshots.

The clients are deliberately transport-injected so tests never require network
and production callers can decide whether live outbound access is allowed.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from complyos.source_intel.models import SourceDefinition, SourceSnapshot, SourceType


class HTTPResponse(BaseModel):
    """Small JSON HTTP response wrapper used by source clients."""

    status_code: int
    data: dict[str, Any]


class HTTPTransport(Protocol):
    """Transport boundary so source clients can run with fake or live HTTP."""

    def get_json(self, url: str, *, params: dict[str, str]) -> HTTPResponse:
        """Fetch JSON from a URL."""


class HttpxTransport:
    """Live HTTP transport using the existing httpx dependency."""

    def __init__(self, *, timeout_seconds: float = 20.0) -> None:
        self.timeout_seconds = timeout_seconds

    def get_json(self, url: str, *, params: dict[str, str]) -> HTTPResponse:
        response = httpx.get(url, params=params, timeout=self.timeout_seconds)
        # Public regulator endpoints routinely answer rate-limit/5xx pages as
        # HTML or empty bodies. Calling .json() unconditionally would raise
        # before the client's status-code coverage-gap branch could run, so we
        # branch on status and content-type first and degrade to empty data.
        content_type = response.headers.get("content-type", "").lower()
        if response.status_code >= 400 or "json" not in content_type:
            return HTTPResponse(status_code=response.status_code, data={})
        try:
            payload = response.json()
        except ValueError:
            return HTTPResponse(status_code=response.status_code, data={})
        return HTTPResponse(
            status_code=response.status_code,
            data=payload if isinstance(payload, dict) else {},
        )


class SourceFetchReport(BaseModel):
    """Result of checking one source through one client."""

    source_id: str
    snapshots: list[SourceSnapshot] = Field(default_factory=list)
    coverage_gaps: list[str] = Field(default_factory=list)


class FederalRegisterClient:
    """Fetch candidate documents from the public Federal Register API."""

    endpoint = "https://www.federalregister.gov/api/v1/documents.json"

    def __init__(self, *, transport: HTTPTransport | None = None) -> None:
        self.transport = transport or HttpxTransport()

    def fetch(self, source: SourceDefinition, *, query: str) -> SourceFetchReport:
        response = self.transport.get_json(
            self.endpoint,
            params={
                "conditions[term]": query,
                "conditions[type][]": "RULE",
                "order": "newest",
                "per_page": "10",
            },
        )
        if response.status_code >= 400:
            return SourceFetchReport(
                source_id=source.id,
                coverage_gaps=[f"Federal Register API returned HTTP {response.status_code}"],
            )

        snapshots = []
        for item in response.data.get("results", []):
            title = str(item.get("title") or "Untitled Federal Register document")
            url = str(item.get("html_url") or source.url)
            abstract = str(item.get("abstract") or "")
            agencies = item.get("agencies") or []
            agency_names = [str(agency.get("name")) for agency in agencies if agency.get("name")]
            text = "\n".join(part for part in [title, abstract, "; ".join(agency_names)] if part)
            snapshots.append(
                SourceSnapshot.from_text(
                    source_id=source.id,
                    url=url,
                    title=title,
                    text=text,
                    metadata={
                        "document_number": item.get("document_number"),
                        "publication_date": item.get("publication_date"),
                        "agencies": agency_names,
                        "source_client": "federal_register",
                    },
                )
            )

        coverage_gaps = [] if snapshots else ["no matching Federal Register documents"]
        return SourceFetchReport(
            source_id=source.id,
            snapshots=snapshots,
            coverage_gaps=coverage_gaps,
        )


class ECFRClient:
    """Fetch candidate sections from the public eCFR search API."""

    endpoint = "https://www.ecfr.gov/api/search/v1/results"

    def __init__(self, *, transport: HTTPTransport | None = None) -> None:
        self.transport = transport or HttpxTransport()

    def fetch(self, source: SourceDefinition, *, query: str) -> SourceFetchReport:
        response = self.transport.get_json(
            self.endpoint,
            params={
                "query": query,
                "title": "29",
                "per_page": "10",
                "page": "1",
            },
        )
        if response.status_code >= 400:
            return SourceFetchReport(
                source_id=source.id,
                coverage_gaps=[f"eCFR API returned HTTP {response.status_code}"],
            )

        snapshots = []
        for item in response.data.get("results", []):
            title = str(item.get("title") or item.get("heading") or "Untitled eCFR result")
            section = str(item.get("section") or "").strip()
            url = (
                f"https://www.ecfr.gov/current/title-29/section-{section}"
                if section
                else source.url
            )
            heading = str(item.get("heading") or "")
            excerpt = str(item.get("full_text_excerpt") or item.get("text") or "")
            hierarchy = item.get("hierarchy_headings") or []
            text = "\n".join(
                part for part in [title, heading, excerpt, " > ".join(map(str, hierarchy))] if part
            )
            snapshots.append(
                SourceSnapshot.from_text(
                    source_id=source.id,
                    url=url,
                    title=title,
                    text=text,
                    metadata={
                        "part": item.get("part"),
                        "section": item.get("section"),
                        "hierarchy_headings": hierarchy,
                        "source_client": "ecfr",
                    },
                )
            )

        coverage_gaps = [] if snapshots else ["no matching eCFR results"]
        return SourceFetchReport(
            source_id=source.id,
            snapshots=snapshots,
            coverage_gaps=coverage_gaps,
        )


def free_public_source_definitions() -> dict[str, SourceDefinition]:
    """Built-in no-paid source definitions for the first RegWatch slice."""
    return {
        "federal-register": SourceDefinition(
            id="federal-register",
            name="Federal Register API",
            url="https://www.federalregister.gov/developers/documentation/api/v1",
            source_type=SourceType.OFFICIAL_REGULATOR,
            authority="official",
            jurisdictions=["US"],
            topics=["federal rules", "workforce training", "compliance"],
            metadata={
                "cost": "free",
                "auth": "none",
                "status": "client-implemented",
                "client": "FederalRegisterClient",
            },
        ),
        "ecfr-title-29": SourceDefinition(
            id="ecfr-title-29",
            name="eCFR Title 29 Search API",
            url="https://www.ecfr.gov/developers/documentation/api/v1",
            source_type=SourceType.OFFICIAL_REGULATOR,
            authority="official",
            jurisdictions=["US"],
            topics=["labor", "workplace safety", "training requirements"],
            metadata={
                "cost": "free",
                "auth": "none",
                "status": "client-implemented",
                "client": "ECFRClient",
            },
        ),
        "osha-web": SourceDefinition(
            id="osha-web",
            name="OSHA Laws and Regulations Web Pages",
            url="https://www.osha.gov/laws-regs",
            source_type=SourceType.OFFICIAL_REGULATOR,
            authority="official",
            jurisdictions=["US"],
            topics=["workplace safety", "training requirements"],
            metadata={
                "cost": "free",
                "auth": "none",
                "status": "web-parser-needed",
                "blocked_reason": "HTML/PDF parser not implemented in this no-paid slice",
            },
        ),
        "california-dir-dlse": SourceDefinition(
            id="california-dir-dlse",
            name="California DIR/DLSE Web Pages",
            url="https://www.dir.ca.gov/dlse/",
            source_type=SourceType.OFFICIAL_REGULATOR,
            authority="official",
            jurisdictions=["US-CA"],
            topics=["labor", "state employment training"],
            metadata={
                "cost": "free",
                "auth": "none",
                "status": "web-parser-needed",
                "blocked_reason": (
                    "jurisdiction-specific parser not implemented in this no-paid slice"
                ),
            },
        ),
    }
