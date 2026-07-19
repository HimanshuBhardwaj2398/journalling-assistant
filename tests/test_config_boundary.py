"""config/ is the only boundary to the environment.

These tests pin the fallback paths that used to bypass it with raw
os.getenv reads (VectorStoreConfig, PDFParser, ingestion service).
"""

import pytest

from config.settings import get_settings
from ingestion.embed import VectorStoreConfig
from ingestion.parsing import PDFParser
from services.ingestion_service import get_orchestrator


@pytest.fixture
def hermetic_settings(monkeypatch, tmp_path):
    """Isolate settings from the process cache AND the developer's .env file.

    Settings read .env relative to CWD; chdir to an empty tmp dir so tests
    exercise pure env-var resolution. AliasChoices order is precedence order,
    so a stray dotenv DB_URL would otherwise beat a monkeypatched DATABASE_URL.
    """
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_vector_store_config_falls_back_to_settings_url(monkeypatch, hermetic_settings):
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/from-settings")

    config = VectorStoreConfig(collection_name="c")

    assert config.db_url == "postgresql://u:p@localhost/from-settings"


def test_pdf_parser_reads_key_via_settings(monkeypatch, hermetic_settings):
    monkeypatch.delenv("LLAMAPARSE_API", raising=False)
    monkeypatch.setenv("PARSING_LLAMAPARSE_API_KEY", "key-from-settings")

    parser = PDFParser()

    assert parser.api_key == "key-from-settings"


def test_get_orchestrator_resolves_url_through_settings(monkeypatch, hermetic_settings):
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/svc")

    orchestrator = get_orchestrator("some_collection")

    assert orchestrator.vector_store_config.db_url == "postgresql://u:p@localhost/svc"


def test_retrieval_engine_defaults_resolve_from_settings(monkeypatch, hermetic_settings):
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/ret")
    monkeypatch.setenv("VECTOR_COLLECTION_NAME", "custom_coll")
    monkeypatch.setenv("EMBEDDING_VOYAGE_MODEL", "voyage-custom")

    from retrieval.query import RetrievalEngine

    engine = RetrievalEngine()

    assert engine._db_url == "postgresql://u:p@localhost/ret"
    assert engine._collection_name == "custom_coll"
    assert engine._embedding_model == "voyage-custom"


def test_collection_service_url_resolves_through_settings(monkeypatch, hermetic_settings):
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/cs")

    from services.collection_service import CollectionService

    service = CollectionService()

    assert service.db_url == "postgresql://u:p@localhost/cs"
