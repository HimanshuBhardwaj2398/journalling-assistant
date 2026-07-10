import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from unittest.mock import MagicMock, patch

from retrieval.query import RetrievalEngine


def test_bm25_search_uses_sql_not_memory(monkeypatch):
    """BM25 search should run SQL FTS, not load all chunks into RAM."""
    engine = RetrievalEngine()

    mock_session = MagicMock()
    mock_session.execute.return_value.fetchall.return_value = []

    with patch("retrieval.query.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        engine._bm25_search("what is mindfulness", k=3)

    assert engine._all_chunks is None  # no in-memory index built
