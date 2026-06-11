"""Database URL resolution tests."""

from __future__ import annotations

from complyos.core.repository import LocalRepository
from complyos.models.database import resolve_database_url
from complyos.models.domain import Course


def test_resolve_database_url_keeps_explicit_sqlalchemy_url() -> None:
    url = "postgresql+psycopg://db.example.invalid:5432/complyos"

    assert resolve_database_url(url) == url


def test_resolve_database_url_uses_environment_override(monkeypatch) -> None:
    monkeypatch.setenv("COMPLYOS_DATABASE_URL", "postgresql+psycopg://env/db")

    assert resolve_database_url("complyos.db") == "postgresql+psycopg://env/db"


def test_resolve_database_url_converts_sqlite_path(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_DATABASE_URL", raising=False)

    assert resolve_database_url("complyos.db") == "sqlite:///complyos.db"


def test_local_repository_accepts_sqlalchemy_database_url(monkeypatch) -> None:
    monkeypatch.delenv("COMPLYOS_DATABASE_URL", raising=False)
    repo = LocalRepository(database_url="sqlite:///:memory:")

    repo.save_course(Course(id="c1", code="SEC-101", title="Security", mandatory=True))

    assert repo.get_course("c1") is not None
