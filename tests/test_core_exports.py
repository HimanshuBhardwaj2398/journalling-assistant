"""The core package facade must export the full exception hierarchy.

If a facade exists, it must be complete — otherwise consumers split
between `from core import X` and `from core.exceptions import X` and the
facade stops being the single door it pretends to be.
"""


def test_all_public_exceptions_importable_from_core():
    from core import (
        CollectionError,
        DatabaseConnectionError,
        DuplicateDocumentError,
        EmbeddingSyncError,
        MeditationDBError,
        VectorStoreError,
    )

    for exc in (
        CollectionError,
        DatabaseConnectionError,
        DuplicateDocumentError,
        EmbeddingSyncError,
        VectorStoreError,
    ):
        assert issubclass(exc, MeditationDBError)
