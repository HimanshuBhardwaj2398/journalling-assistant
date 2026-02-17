"""Tests for chunk metadata restructure."""

import sys
from pathlib import Path

# Avoid triggering ingestion/__init__.py which imports llama_cloud_services
sys.modules.setdefault("ingestion", type(sys)("ingestion"))

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


class TestAddFinalMetadata:
    """Tests for _add_final_metadata with new metadata format."""

    def setup_method(self):
        self.chunker = MarkdownChunker(
            text="# Test Doc\nSome content",
            config=Config(enable_semantic=False),
            title="Test Doc",
        )

    def test_single_header_chunk(self):
        """Non-combined chunk gets single path in all_header_paths."""
        chunks = [
            Document(
                page_content="Some content about meditation.",
                metadata={"Header 1": "Digha Nikaya", "Header 2": "Sutta 1"},
            )
        ]
        result = self.chunker._add_final_metadata(chunks)
        meta = result[0].metadata

        assert meta["all_header_paths"] == ["Digha Nikaya > Sutta 1"]
        assert meta["header_level_map"] == {"Digha Nikaya": 1, "Sutta 1": 2}
        assert meta["doc_title"] == "Test Doc"
        assert meta["word_count"] == 4
        assert meta["char_count"] == 30
        # Old fields must be gone
        assert "Header 1" not in meta
        assert "Header 2" not in meta
        assert "primary_header" not in meta
        assert "header_level" not in meta
        assert "section_path" not in meta
        assert "chunk_index" not in meta

    def test_combined_chunk_with_all_headers(self):
        """Combined chunk with all_headers gets multiple paths."""
        chunks = [
            Document(
                page_content="Content spanning sections.",
                metadata={
                    "Header 1": "DN",
                    "Header 2": "Sutta 1",
                    "is_combined": True,
                    "all_headers": [
                        {"Header 1": "DN", "Header 2": "Sutta 1"},
                        {"Header 1": "DN", "Header 2": "Sutta 2"},
                    ],
                },
            )
        ]
        result = self.chunker._add_final_metadata(chunks)
        meta = result[0].metadata

        assert meta["all_header_paths"] == ["DN > Sutta 1", "DN > Sutta 2"]
        assert meta["header_level_map"] == {"DN": 1, "Sutta 1": 2, "Sutta 2": 2}
        assert meta["is_combined"] is True
        assert "all_headers" not in meta
        assert "Header 1" not in meta

    def test_chunk_with_no_headers(self):
        """Chunk without headers gets empty paths."""
        chunks = [
            Document(page_content="Standalone content.", metadata={})
        ]
        result = self.chunker._add_final_metadata(chunks)
        meta = result[0].metadata

        assert meta["all_header_paths"] == []
        assert meta["header_level_map"] == {}
        assert meta["doc_title"] == "Test Doc"

    def test_is_semantic_split_preserved(self):
        """is_semantic_split flag survives transformation."""
        chunks = [
            Document(
                page_content="Split content.",
                metadata={"Header 1": "Title", "is_semantic_split": True},
            )
        ]
        result = self.chunker._add_final_metadata(chunks)
        assert result[0].metadata["is_semantic_split"] is True
