"""Resilience tests for source-intelligence live fetch (WP3 / H5).

Public regulator endpoints (Federal Register, eCFR) return rate-limit and
server-error pages as HTML or empty bodies. The transport must not crash on a
non-JSON body, and one failing source must not abort the whole monitor run.
"""

from __future__ import annotations

import httpx
import respx

from complyos.source_intel.clients import (
    FederalRegisterClient,
    HttpxTransport,
    SourceFetchReport,
    free_public_source_definitions,
)
from complyos.source_intel.models import SourceDefinition, SourceSnapshot
from complyos.source_intel.monitor import SourceMonitor

ENDPOINT = "https://www.federalregister.gov/api/v1/documents.json"


@respx.mock
def test_transport_returns_empty_data_on_5xx_html_body() -> None:
    respx.get(ENDPOINT).mock(return_value=httpx.Response(503, html="<html>rate limited</html>"))
    response = HttpxTransport().get_json(ENDPOINT, params={})
    assert response.status_code == 503
    assert response.data == {}


@respx.mock
def test_transport_returns_empty_data_on_200_non_json() -> None:
    respx.get(ENDPOINT).mock(return_value=httpx.Response(200, text="not json"))
    response = HttpxTransport().get_json(ENDPOINT, params={})
    assert response.status_code == 200
    assert response.data == {}


@respx.mock
def test_transport_parses_valid_json() -> None:
    respx.get(ENDPOINT).mock(return_value=httpx.Response(200, json={"results": []}))
    response = HttpxTransport().get_json(ENDPOINT, params={})
    assert response.status_code == 200
    assert response.data == {"results": []}


@respx.mock
def test_client_reports_coverage_gap_instead_of_crashing_on_5xx() -> None:
    respx.get(ENDPOINT).mock(return_value=httpx.Response(503, html="<html>down</html>"))
    source = free_public_source_definitions()["federal-register"]

    report = FederalRegisterClient().fetch(source, query="training")

    assert report.snapshots == []
    assert any("HTTP 503" in gap for gap in report.coverage_gaps)


class _RaisingClient:
    def fetch(self, source: SourceDefinition, *, query: str) -> SourceFetchReport:
        raise httpx.ConnectError("boom")


class _HealthyClient:
    def fetch(self, source: SourceDefinition, *, query: str) -> SourceFetchReport:
        return SourceFetchReport(
            source_id=source.id,
            snapshots=[
                SourceSnapshot.from_text(
                    source_id=source.id,
                    url=source.url,
                    title="ok",
                    text="healthy snapshot",
                    metadata={},
                )
            ],
        )


class _FakeEngine:
    def evaluate(self, sources, snapshots):  # noqa: ANN001 - test double
        return []


def test_monitor_degrades_when_one_source_raises() -> None:
    sources = list(free_public_source_definitions().values())[:2]
    failing, healthy = sources[0], sources[1]
    monitor = SourceMonitor(
        sources=sources,
        clients={failing.id: _RaisingClient(), healthy.id: _HealthyClient()},
        engine=_FakeEngine(),
    )

    run = monitor.run(query="training")

    # The run completes and preserves the healthy source's snapshot.
    assert run.snapshot_count == 1
    assert any("fetch failed" in gap and failing.id in gap for gap in run.coverage_gaps)
