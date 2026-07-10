"""
Database connection and session management.
Supports both local PostgreSQL and Supabase with optimized pooling.
"""

import logging
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from config.settings import get_settings

from .schema import Base

logger = logging.getLogger(__name__)

# Get settings
settings = get_settings()

# Configure engine based on environment
if settings.database.is_remote:
    # Managed/remote Postgres (Neon, etc.): connection resilience for providers
    # that suspend idle connections (Neon scale-to-zero) and drop them mid-pool.
    # SSL is taken from the URL (append ?sslmode=require) rather than connect_args,
    # so sslmode is never specified twice.
    engine = create_engine(
        settings.database.url,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_timeout=settings.database.pool_timeout,
        pool_recycle=settings.database.pool_recycle,  # recycle stale connections proactively
        pool_pre_ping=True,  # validate + transparently reconnect before use
        echo=settings.database.echo,
        connect_args={
            "connect_timeout": 10,  # Fail fast if connection takes >10s
            "keepalives": 1,  # Enable TCP keepalives
            "keepalives_idle": 30,  # Start keepalives after 30s idle
            "keepalives_interval": 10,  # Send keepalive every 10s
            "keepalives_count": 5,  # Give up after 5 failed keepalives
        },
    )
    logger.info("Initialized remote (managed) database connection with resilient pooling")
else:
    # Local development configuration
    engine = create_engine(
        settings.database.url,
        pool_size=5,
        max_overflow=10,
        echo=settings.database.echo,
    )
    logger.info("Initialized local database connection")

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    Initialize database: create pgvector extension and all tables.

    This should be run once when setting up a new database.
    For Supabase, ensure pgvector extension is enabled.
    """
    logger.info("Initializing database...")

    try:
        # Create pgvector extension
        with engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
            logger.info("✓ pgvector extension enabled")

        # Create all tables
        Base.metadata.create_all(bind=engine)
        logger.info("✓ Database tables created")

        # Verify tables
        with engine.connect() as connection:
            result = connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = [row[0] for row in result]
            logger.info(f"✓ Tables in database: {', '.join(tables)}")

        logger.info("Database initialization complete")

    except Exception as e:
        logger.error(f"Database initialization failed: {e}", exc_info=True)
        raise


# def get_engine():
#     """Returns the SQLAlchemy engine for database operations.
#     This is useful for raw SQL queries or when you need to execute database commands directly.
#     """

#     DATABASE_URL = os.getenv("DATABASE_URL")

#     if not DATABASE_URL:
#         raise ValueError("DATABASE_URL environment variable not set in .env file")

#     # The engine is the entry point to the database.
#     # `echo=False` is recommended for production.
#     engine = create_engine(DATABASE_URL, echo=False)

#     # A sessionmaker is a factory for creating Session objects.
# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@contextmanager
def session_scope():
    """
    Provide a transactional scope around database operations.

    Usage:
        with session_scope() as session:
            doc = DocumentCRUD(session).create_document(...)
            session.commit()
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        logger.error(f"Session error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def get_db():
    """
    A generator function to provide a database session for each request.
    This ensures the session is always closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
