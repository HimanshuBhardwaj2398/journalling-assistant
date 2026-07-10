"""Tests for the injectable Database (dependency-inverted persistence)."""

from sqlalchemy import text

from config.settings import DatabaseSettings
from db.database import Database


def test_database_session_scope_yields_working_session():
    """A Database can be built from any settings and hand out working sessions —
    no module-level global, no environment variable, no real Postgres required."""
    db = Database(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))

    with db.session_scope() as session:
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_database_does_not_build_engine_until_first_use():
    """Constructing a Database must not connect or build an engine (lazy)."""
    db = Database(DatabaseSettings(url="postgresql://u:p@ep-x.neon.tech/db?sslmode=require"))

    assert db._engine is None
