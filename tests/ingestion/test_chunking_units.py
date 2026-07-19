"""Chunk-merging thresholds are measured in characters, matching config docs.

Historically `_combine_small_chunks` measured the current chunk in *words*
while accumulating *characters*, so `min_size`/`tiny_chunk_threshold`
(documented as characters) silently meant different things in different
comparisons. These tests pin character semantics with cases where the two
interpretations disagree.
"""

from langchain.schema import Document

from ingestion.chunking import Config, MarkdownChunker


def make_chunker(**overrides) -> MarkdownChunker:
    config = Config(enable_semantic=False, enable_parallel=False, **overrides)
    return MarkdownChunker(text="# Title\n\nbody", config=config)


def test_few_long_words_are_not_tiny():
    """5 words / 174 chars with tiny_chunk_threshold=20: not tiny in chars.

    Word-based measuring would call this tiny (5 < 20) and merge it away.
    """
    long_words = ("supercalifragilisticexpialidocious " * 5).strip()
    assert len(long_words.split()) == 5
    assert len(long_words) >= 100

    chunker = make_chunker(max_size=300, min_size=100, tiny_chunk_threshold=20)
    chunks = [
        Document(page_content=long_words, metadata={}),
        Document(page_content="y" * 150, metadata={}),
    ]

    merged = chunker._combine_small_chunks(chunks)

    assert len(merged) == 2


def test_many_short_words_meeting_min_chars_stay_standalone():
    """80 words / ~400 chars with min_size=300: large enough in chars.

    Word-based measuring would call this small (80 < 300) and start merging.
    """
    content = ("word " * 79) + "word"
    assert len(content.split()) == 80
    assert len(content) >= 300

    chunker = make_chunker(max_size=1000, min_size=300, tiny_chunk_threshold=50)
    chunks = [
        Document(page_content=content, metadata={}),
        Document(page_content="z" * 400, metadata={}),
    ]

    merged = chunker._combine_small_chunks(chunks)

    assert len(merged) == 2


def test_combining_accumulates_characters_and_stops_at_min_size():
    chunker = make_chunker(max_size=1000, min_size=180, tiny_chunk_threshold=10)
    chunks = [
        Document(page_content="a" * 100, metadata={}),
        Document(page_content="b" * 90, metadata={}),
        Document(page_content="c" * 150, metadata={}),
    ]

    merged = chunker._combine_small_chunks(chunks)

    assert len(merged) == 2
    # 100 + "\n\n" + 90
    assert len(merged[0].page_content) == 192
