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


def test_set_default_database_overrides_the_process_default():
    """A composition root (e.g. an ingestion CLI) can point the default DB elsewhere."""
    import db.database as db_module
    from db.database import get_database, set_default_database

    original = db_module._default_database
    try:
        db = Database(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))
        set_default_database(db)
        assert get_database() is db
    finally:
        db_module._default_database = original
