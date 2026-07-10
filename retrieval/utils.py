"""Shared utilities for the retrieval layer."""


def extract_header_paths(metadata: dict | None) -> list[str]:
    """Return a normalized list of header paths from chunk metadata."""
    if not isinstance(metadata, dict):
        return []

    paths: list[str] = []

    def add(raw: object) -> None:
        if not isinstance(raw, str):
            return
        cleaned = " > ".join(part.strip() for part in raw.split(">") if part.strip())
        if cleaned and cleaned not in paths:
            paths.append(cleaned)

    all_header_paths = metadata.get("all_header_paths", [])
    if isinstance(all_header_paths, str):
        add(all_header_paths)
    elif isinstance(all_header_paths, list):
        for path in all_header_paths:
            add(path)

    add(metadata.get("header_path"))
    add(metadata.get("section_path"))

    if not paths:
        legacy_headers = []
        for level in range(1, 7):
            value = metadata.get(f"Header {level}")
            if isinstance(value, str) and value.strip():
                legacy_headers.append(value.strip())
        if legacy_headers:
            paths.append(" > ".join(legacy_headers))

    return paths
