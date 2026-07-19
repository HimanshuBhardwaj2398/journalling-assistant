import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from unittest.mock import MagicMock, patch

from retrieval.query import RetrievalEngine


def test_fts_search_runs_sql_against_tsv_column(monkeypatch):
    """FTS runs SQL against the generated tsvector column, not in-memory."""
    engine = RetrievalEngine()

    mock_session = MagicMock()
    mock_session.execute.return_value.fetchall.return_value = []

    with patch("retrieval.query.session_scope") as mock_scope:
        mock_scope.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_scope.return_value.__exit__ = MagicMock(return_value=False)
        engine._fts_search("what is mindfulness", k=3)

    executed_sql = str(mock_session.execute.call_args[0][0])
    assert "chunk_text_tsv" in executed_sql
