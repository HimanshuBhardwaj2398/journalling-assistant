# file: models.py

import os
from sqlalchemy import (
    create_engine,
    Column,
    Text,
    DateTime,
    BigInteger,  # Use BigInteger to match PostgreSQL's BIGSERIAL
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func  # To use SQL functions like NOW()

# Import PostgreSQL-specific types
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

# --- Step 1: Set up the Base Class ---
# All our ORM models will inherit from this class.
Base = declarative_base()


# --- Step 2: Define the Document Class ---
# This class maps to the 'documents' table in PostgreSQL.


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True)
    title = Column(Text, nullable=False)
    markdown = Column(Text)
    doc_metadata = Column(JSONB)  # For storing document metadata
    tags = Column(ARRAY(Text))
    description = Column(Text)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),  # Important for SQLAlchemy to know this is updated
        nullable=False,
    )

    def __repr__(self):
        """Provides a developer-friendly representation of the object."""
        return f"<Document(id={self.id}, title='{self.title}')>"
