"""Tests for configuration management."""

from __future__ import annotations

from complyos.config import ComplyOSConfig, generate_config


class TestComplyOSConfig:
    def test_load_from_path(self, tmp_path):
        config_file = tmp_path / "complyos.yaml"
        config_file.write_text("connector:\n  type: workday\n")
        config = ComplyOSConfig.load(str(config_file))
        assert config.connector["type"] == "workday"

    def test_load_missing_returns_empty(self, tmp_path):
        config = ComplyOSConfig.load(str(tmp_path / "nonexistent.yaml"))
        assert config._data == {}
        assert config.connector == {}
        assert config.database == {}
        assert config.defaults == {}

    def test_get_with_default(self):
        config = ComplyOSConfig({})
        assert config.get("foo", "bar") == "bar"

    def test_generate_config(self):
        text = generate_config(connector_type="workday", db_path="test.db")
        assert "workday" in text
        assert "test.db" in text
        assert "WORKDAY_BASE_URL" in text

    def test_load_from_default_paths(self, tmp_path, monkeypatch):
        config_file = tmp_path / "complyos.yaml"
        config_file.write_text("database:\n  path: custom.db\n")
        monkeypatch.chdir(tmp_path)
        config = ComplyOSConfig.load()
        assert config.database["path"] == "custom.db"


def test_database_path_uses_config_or_default():
    config = ComplyOSConfig({"database": {"path": "configured.db"}})
    assert config.database_path() == "configured.db"
    assert ComplyOSConfig({}).database_path() == "complyos.db"
