"""
This module handles the database connection and session management for the application.
"""

import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from .schema import Base  # Import Base from schema.py
import logging

## import context manager for session handling
from contextlib import contextmanager

# Load the .env file from the project root
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=dotenv_path)

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set in .env file")

# The engine is the entry point to the database.
# `echo=False` is recommended for production.
engine = create_engine(DATABASE_URL, echo=False)

# A sessionmaker is a factory for creating Session objects.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """
    Initializes the database and creates tables based on the SQLAlchemy models.
    Call this function once when your application starts up.
    """
    print("Initializing database and creating tables...")
    with engine.connect() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.commit()
    # This creates the tables defined in schema.py
    Base.metadata.create_all(bind=engine)
    print("Database initialized successfully.")


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
    Provide a transactional scope around a series of database operations.
    This is the recommended way to handle sessions.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        logging.info("Session rolled back due to an exception.")
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
