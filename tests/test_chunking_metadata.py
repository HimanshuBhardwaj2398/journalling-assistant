"""Tests for chunk metadata restructure."""

import pytest
from langchain.schema import Document
from ingestion.chunking import MarkdownChunker, Config


class TestBuildHeaderPath:
    """Tests for _build_header_path helper."""

    def setup_method(self):
        self.chunker = MarkdownChunker(
            text="# Test\nSome content",
            config=Config(enable_semantic=False),
        )

    def test_single_header(self):
        header_dict = {"Header 1": "Introduction"}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Introduction"
        assert level_map == {"Introduction": 1}

    def test_nested_headers(self):
        header_dict = {"Header 1": "Digha Nikaya", "Header 2": "Brahmajala Sutta", "Header 3": "Chapter 1"}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Digha Nikaya > Brahmajala Sutta > Chapter 1"
        assert level_map == {"Digha Nikaya": 1, "Brahmajala Sutta": 2, "Chapter 1": 3}

    def test_skipped_levels(self):
        header_dict = {"Header 1": "Title", "Header 3": "Deep Section"}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Title > Deep Section"
        assert level_map == {"Title": 1, "Deep Section": 3}

    def test_empty_dict(self):
        path, level_map = self.chunker._build_header_path({})
        assert path == ""
        assert level_map == {}

    def test_non_header_keys_ignored(self):
        header_dict = {"Header 1": "Title", "is_combined": True, "chunk_index": 0}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Title"
        assert level_map == {"Title": 1}
