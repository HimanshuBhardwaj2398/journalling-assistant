import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from langchain_core.documents import Document

from retrieval.query import RetrievalEngine


def _make_doc(content: str, uuid: str | None = None) -> Document:
    meta = {}
    if uuid:
        meta["uuid"] = uuid
    return Document(page_content=content, metadata=meta)


def test_rrf_dedup_uses_uuid_when_available():
    engine = RetrievalEngine.__new__(RetrievalEngine)
    doc = _make_doc("some text here", uuid="abc-123")
    result = engine._reciprocal_rank_fusion([[doc], [doc]], weights=[0.5, 0.5], k=5)
    # Same doc (same UUID) should appear only once
    assert len(result) == 1


def test_rrf_dedup_uses_hash_when_no_uuid():
    engine = RetrievalEngine.__new__(RetrievalEngine)
    doc = _make_doc("some text here")
    result = engine._reciprocal_rank_fusion([[doc], [doc]], weights=[0.5, 0.5], k=5)
    assert len(result) == 1


def test_minmax_normalization_bounds():
    from retrieval.query import _minmax_normalize
    scores = [0.2, 0.5, 0.8, 1.0]
    normed = _minmax_normalize(scores)
    assert normed[0] == 0.0
    assert normed[-1] == 1.0
    assert all(0.0 <= s <= 1.0 for s in normed)


def test_minmax_normalization_all_same():
    from retrieval.query import _minmax_normalize
    # Should not divide by zero
    normed = _minmax_normalize([0.5, 0.5, 0.5])
    assert normed == [0.5, 0.5, 0.5]
