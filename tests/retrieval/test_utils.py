from retrieval.utils import extract_header_paths


def test_extract_from_all_header_paths_list():
    meta = {"all_header_paths": ["Foo > Bar", "Foo > Baz"]}
    assert extract_header_paths(meta) == ["Foo > Bar", "Foo > Baz"]


def test_extract_from_header_path_string():
    meta = {"header_path": "A > B > C"}
    assert extract_header_paths(meta) == ["A > B > C"]


def test_deduplication():
    meta = {"all_header_paths": ["A > B"], "header_path": "A > B"}
    assert extract_header_paths(meta) == ["A > B"]


def test_legacy_headers_fallback():
    meta = {"Header 1": "Digha Nikaya", "Header 2": "Chapter 1"}
    assert extract_header_paths(meta) == ["Digha Nikaya > Chapter 1"]


def test_empty_metadata():
    assert extract_header_paths(None) == []
    assert extract_header_paths({}) == []
