"""Tests for connector capability metadata."""

from __future__ import annotations

from complyos.connectors.capabilities import list_connector_capabilities


def _by_name(profile: str | None = None):
    return {item.name: item for item in list_connector_capabilities(profile=profile)}


def test_matrix_contains_key_workforce_connectors():
    names = set(_by_name(profile="workforce"))

    assert {"csv", "workday", "cornerstone", "successfactors", "docebo", "absorb"} <= names


def test_matrix_contains_key_campus_connectors():
    names = set(_by_name(profile="campus"))

    assert {"csv", "canvas", "brightspace", "blackboard", "moodle"} <= names


def test_canvas_capabilities_include_learning_records_and_due_dates():
    canvas = _by_name(profile="campus")["canvas"]

    assert canvas.profile == "campus"
    assert canvas.supports_learning_records is True
    assert canvas.supports_due_dates is True
    assert canvas.supports_exemptions is True
    assert canvas.supports_scores is True
    # Canvas has no native recertification/expiry field.
    assert canvas.supports_expiry is False
    # Canvas connector is implemented (Bearer API token).
    assert canvas.status == "supported"
    assert canvas.auth == "token"


def test_csv_is_supported_for_both_tracks():
    csv = _by_name()["csv"]

    assert csv.profile == "both"
    assert csv.status == "supported"
    assert csv.supports_users is True
    assert csv.supports_courses is True
    assert csv.supports_learning_records is True


def test_phase_five_workforce_connectors_are_supported():
    items = _by_name(profile="workforce")

    assert items["cornerstone"].status == "supported"
    assert items["successfactors"].status == "supported"


def test_matrix_rejects_unknown_profile():
    import pytest

    with pytest.raises(ValueError, match="Unknown connector profile 'unknown'"):
        list_connector_capabilities(profile="unknown")


def test_matrix_normalizes_profile_whitespace_and_case():
    names = set(_by_name(profile=" Workforce "))

    assert "cornerstone" in names


def test_workday_supported_but_expiry_not_advertised_until_parsed():
    workday = _by_name(profile="workforce")["workday"]

    assert workday.status == "supported"
    # WorkdayConnector does not parse recertification/expiry fields yet.
    assert workday.supports_expiry is False
