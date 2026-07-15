"""Unique index on documents.file_path; generated tsvector + GIN index on chunks

documents.file_path backs the ingestion dup guard (`check_duplicate`); the
unique index makes the database enforce what the application only advised
(two concurrent ingests of the same source can no longer both insert).

chunks.chunk_text_tsv is a stored generated column so hybrid search's FTS
leg hits a GIN index instead of recomputing to_tsvector('english', ...)
per row per query.

Revision ID: b7c9d1e3f5a7
Revises: 1367bf7a9116
Create Date: 2026-07-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c9d1e3f5a7"
down_revision: Union[str, Sequence[str], None] = "1367bf7a9116"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index("ix_documents_file_path", "documents", ["file_path"], unique=True)
    op.add_column(
        "chunks",
        sa.Column(
            "chunk_text_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', chunk_text)", persisted=True),
            nullable=True,
            comment="Generated tsvector powering GIN-indexed full-text search",
        ),
    )
    op.create_index(
        "ix_chunks_chunk_text_tsv",
        "chunks",
        ["chunk_text_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_chunks_chunk_text_tsv", table_name="chunks")
    op.drop_column("chunks", "chunk_text_tsv")
    op.drop_index("ix_documents_file_path", table_name="documents")
