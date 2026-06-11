"""CLI tests for connector capability matrix."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_connectors_workforce_profile_filters_out_campus_connectors():
    result = runner.invoke(app, ["connectors", "--profile", "workforce"])

    assert result.exit_code == 0
    assert "cornerstone" in result.output
    assert "successfactors" in result.output
    assert "canvas" not in result.output


def test_connectors_campus_json_filters_out_workforce_connectors():
    result = runner.invoke(app, ["connectors", "--profile", "campus", "--json"])

    assert result.exit_code == 0
    data = json.loads(result.output)
    names = {item["name"] for item in data}
    assert {"canvas", "brightspace"} <= names
    assert "cornerstone" not in names
