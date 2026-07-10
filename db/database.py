"""
Database connection and session management.

The engine is owned by a :class:`Database` object constructed on demand rather
than at import time, so importing this module no longer requires database
configuration (the seam that makes persistence injectable and testable). A
lazily-built default ``Database`` (from application settings) backs the
backward-compatible module-level ``session_scope`` / ``init_db`` / ``get_db``
helpers and the ``engine`` / ``SessionLocal`` attributes.
"""

import logging
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import DatabaseSettings, get_settings

from .schema import Base

logger = logging.getLogger(__name__)


class Database:
    """Owns a SQLAlchemy engine + session factory for a single database.

    Built lazily on first use, so it can be injected freely — including with an
    in-memory SQLite URL in tests — without touching globals or environment
    variables.
    """

    def __init__(self, settings: DatabaseSettings):
        self._settings = settings
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            self._engine = self._build_engine(self._settings)
            self._session_factory = sessionmaker(
                autocommit=False, autoflush=False, bind=self._engine
            )
            logger.info("Initialized database engine")
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        if self._session_factory is None:
            _ = self.engine  # building the engine also builds the session factory
        return self._session_factory

    @staticmethod
    def _build_engine(settings: DatabaseSettings) -> Engine:
        url = settings.url
        if url.startswith("sqlite"):
            # SQLite (tests/local): no server-side pooling knobs.
            return create_engine(url, echo=settings.echo)
        if settings.is_remote:
            # Managed/remote Postgres (Neon, etc.): resilient pooling; SSL from the URL.
            return create_engine(
                url,
                pool_size=settings.pool_size,
                max_overflow=settings.max_overflow,
                pool_timeout=settings.pool_timeout,
                pool_recycle=settings.pool_recycle,
                pool_pre_ping=True,
                echo=settings.echo,
                connect_args={
                    "connect_timeout": 10,
                    "keepalives": 1,
                    "keepalives_idle": 30,
                    "keepalives_interval": 10,
                    "keepalives_count": 5,
                },
            )
        return create_engine(url, pool_size=5, max_overflow=10, echo=settings.echo)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Provide a transactional scope around a series of operations."""
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception as exc:
            logger.error(f"Session error: {exc}")
            session.rollback()
            raise
        finally:
            session.close()

    def init_db(self) -> None:
        """Create the pgvector extension and all tables. Run once per database."""
        logger.info("Initializing database...")
        try:
            with self.engine.connect() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                connection.commit()
                logger.info("pgvector extension enabled")

            Base.metadata.create_all(bind=self.engine)
            logger.info("Database tables created")

            with self.engine.connect() as connection:
                result = connection.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                        "ORDER BY tablename"
                    )
                )
                tables = [row[0] for row in result]
                logger.info(f"Tables in database: {', '.join(tables)}")

            logger.info("Database initialization complete")
        except Exception as exc:
            logger.error(f"Database initialization failed: {exc}", exc_info=True)
            raise


# ---------------------------------------------------------------------------
# Backward-compatible module-level API (delegates to a lazily-built default DB)
# ---------------------------------------------------------------------------

_default_database: Optional[Database] = None


def get_database() -> Database:
    """Return the process-wide default Database, built from application settings."""
    global _default_database
    if _default_database is None:
        _default_database = Database(get_settings().database)
    return _default_database


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope backed by the default database (backward-compatible).

    Usage:
        with session_scope() as session:
            DocumentCRUD(session).create_document(...)
    """
    with get_database().session_scope() as session:
        yield session


def get_db() -> Iterator[Session]:
    """Yield a session from the default database (e.g. for request handlers)."""
    session = get_database().session_factory()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """Initialize the default database (pgvector extension + tables)."""
    get_database().init_db()


def __getattr__(name: str):
    """Lazily expose ``engine`` / ``SessionLocal`` without building them at import."""
    if name == "engine":
        return get_database().engine
    if name == "SessionLocal":
        return get_database().session_factory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
