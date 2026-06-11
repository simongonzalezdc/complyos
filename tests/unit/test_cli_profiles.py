"""CLI tests for profile initialization."""

from __future__ import annotations

from typer.testing import CliRunner

from complyos.cli import app

runner = CliRunner()


def test_init_workforce_profile_writes_config(tmp_path):
    output = tmp_path / "complyos.yaml"

    result = runner.invoke(app, ["init", "--profile", "workforce", "--output", str(output)])

    assert result.exit_code == 0
    assert "Initialized ComplyOS Workforce" in result.output
    assert output.exists()
    content = output.read_text()
    assert "profile: workforce" in content
    assert "learner_term: employee" in content


def test_init_campus_profile_writes_config(tmp_path):
    output = tmp_path / "campus.yaml"

    result = runner.invoke(app, ["init", "--profile", "campus", "--output", str(output)])

    assert result.exit_code == 0
    assert "Initialized ComplyOS Campus" in result.output
    assert output.exists()
    content = output.read_text()
    assert "profile: campus" in content
    assert "learner_term: student" in content


def test_init_unknown_profile_exits_one_without_writing_output(tmp_path):
    output = tmp_path / "unknown.yaml"

    result = runner.invoke(app, ["init", "--profile", "unknown", "--output", str(output)])

    assert result.exit_code == 1
    assert "Unknown ComplyOS profile" in result.output
    assert not output.exists()
