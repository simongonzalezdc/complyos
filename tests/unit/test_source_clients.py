from __future__ import annotations

from complyos.source_intel import SourceType
from complyos.source_intel.clients import (
    ECFRClient,
    FederalRegisterClient,
    HTTPResponse,
    SourceFetchReport,
    free_public_source_definitions,
)


class FakeTransport:
    def __init__(self, responses: dict[str, HTTPResponse]) -> None:
        self.responses = responses
        self.urls: list[str] = []

    def get_json(self, url: str, *, params: dict[str, str]) -> HTTPResponse:
        self.urls.append(f"{url}?{params}")
        return self.responses[url]


def test_federal_register_client_builds_snapshot_from_public_api_payload() -> None:
    transport = FakeTransport(
        {
            "https://www.federalregister.gov/api/v1/documents.json": HTTPResponse(
                status_code=200,
                data={
                    "results": [
                        {
                            "document_number": "2026-12345",
                            "title": "Final rule updates safety training",
                            "abstract": "Covered employers must train workers by July 1, 2027.",
                            "html_url": "https://www.federalregister.gov/documents/2026/01/01/example",
                            "publication_date": "2026-01-01",
                            "agencies": [{"name": "Occupational Safety and Health Administration"}],
                        }
                    ]
                },
            )
        }
    )
    source = free_public_source_definitions()["federal-register"]

    report = FederalRegisterClient(transport=transport).fetch(source, query="training")

    assert isinstance(report, SourceFetchReport)
    assert report.source_id == "federal-register"
    assert report.coverage_gaps == []
    assert len(report.snapshots) == 1
    snapshot = report.snapshots[0]
    assert snapshot.title == "Final rule updates safety training"
    assert "Covered employers must train workers" in snapshot.text
    assert snapshot.url.startswith("https://www.federalregister.gov/documents/")
    assert snapshot.metadata["document_number"] == "2026-12345"
    assert snapshot.metadata["publication_date"] == "2026-01-01"


def test_ecfr_client_builds_snapshot_and_reports_empty_results_as_coverage_gap() -> None:
    source = free_public_source_definitions()["ecfr-title-29"]
    empty_transport = FakeTransport(
        {
            "https://www.ecfr.gov/api/search/v1/results": HTTPResponse(
                status_code=200,
                data={"results": []},
            )
        }
    )

    empty_report = ECFRClient(transport=empty_transport).fetch(source, query="training")

    assert empty_report.snapshots == []
    assert "no matching eCFR results" in empty_report.coverage_gaps

    filled_transport = FakeTransport(
        {
            "https://www.ecfr.gov/api/search/v1/results": HTTPResponse(
                status_code=200,
                data={
                    "results": [
                        {
                            "title": "29 CFR 1910.1200",
                            "heading": "Hazard communication training",
                            "full_text_excerpt": "Employers shall provide effective training.",
                            "hierarchy_headings": ["Labor", "Occupational Safety"],
                            "part": "1910",
                            "section": "1200",
                        }
                    ]
                },
            )
        }
    )

    report = ECFRClient(transport=filled_transport).fetch(source, query="training")

    assert len(report.snapshots) == 1
    snapshot = report.snapshots[0]
    assert snapshot.source_id == "ecfr-title-29"
    assert "Employers shall provide effective training" in snapshot.text
    assert snapshot.url == "https://www.ecfr.gov/current/title-29/section-1200"
    assert snapshot.metadata["part"] == "1910"
    assert snapshot.metadata["section"] == "1200"


def test_free_public_source_definitions_mark_auth_and_cost_boundaries() -> None:
    sources = free_public_source_definitions()

    assert sources["federal-register"].source_type == SourceType.OFFICIAL_REGULATOR
    assert sources["federal-register"].metadata["cost"] == "free"
    assert sources["federal-register"].metadata["auth"] == "none"
    assert sources["ecfr-title-29"].metadata["cost"] == "free"
    assert sources["osha-web"].metadata["status"] == "web-parser-needed"
