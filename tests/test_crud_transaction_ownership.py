"""Contract tests: CRUD methods must never end the transaction.

The unit of work belongs to the caller's ``session_scope`` — CRUD methods
flush (so IDs materialize and constraint errors surface early) but never
commit. A CRUD-level commit would make multi-step operations non-atomic:
an interior commit is durable even if a later step in the same scope fails.
"""

from unittest.mock import MagicMock

import pytest

from db.crud import ChunkCRUD, DocumentCRUD
from db.schema import DocumentStatus


def _session_with_row():
    """Mock session whose query chain returns a row with real dict metadata."""
    session = MagicMock()
    row = MagicMock()
    row.doc_metadata = {"existing": "value"}
    row.chunk_metadata = {"existing": "value"}
    session.query.return_value.filter.return_value.first.return_value = row
    return session


MUTATING_OPERATIONS = [
    (
        "create_document",
        lambda s: DocumentCRUD(s).create_document(title="T", file_path="src.pdf"),
    ),
    (
        "update_status",
        lambda s: DocumentCRUD(s).update_status(1, DocumentStatus.COMPLETED, "done"),
    ),
    (
        "update_markdown",
        lambda s: DocumentCRUD(s).update_markdown(1, "# md"),
    ),
    (
        "update_doc_metadata",
        lambda s: DocumentCRUD(s).update_doc_metadata(1, {"k": "v"}, merge=True),
    ),
    (
        "clear_chunks",
        lambda s: DocumentCRUD(s).clear_chunks(1),
    ),
    (
        "delete_document",
        lambda s: DocumentCRUD(s).delete_document(1),
    ),
    (
        "create_chunks_batch",
        lambda s: ChunkCRUD(s).create_chunks_batch(
            1, [{"uuid": "u-1", "chunk_text": "t", "chunk_index": 0}]
        ),
    ),
    (
        "update_chunk_metadata",
        lambda s: ChunkCRUD(s).update_chunk_metadata(1, {"k": "v"}, merge=True),
    ),
    (
        "delete_chunks_by_document",
        lambda s: ChunkCRUD(s).delete_chunks_by_document(1),
    ),
]


@pytest.mark.parametrize(
    "name,operation", MUTATING_OPERATIONS, ids=[case[0] for case in MUTATING_OPERATIONS]
)
def test_crud_method_does_not_commit(name, operation):
    """No CRUD method may commit — the enclosing session_scope owns that."""
    session = _session_with_row()

    operation(session)

    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "name,operation",
    [case for case in MUTATING_OPERATIONS if case[0] in ("create_document", "create_chunks_batch")],
    ids=["create_document", "create_chunks_batch"],
)
def test_create_operations_flush_so_ids_materialize(name, operation):
    """Creates must flush: callers read .id inside the scope, before commit."""
    session = _session_with_row()

    operation(session)

    session.flush.assert_called()
