"""CHUNKING_* environment settings must actually reach the chunker.

Config.from_settings() is the bridge from env-driven ChunkingSettings to
the chunker's Config; the orchestrator uses it as its default so that
documented env vars are not decorative.
"""

from ingestion.chunking import Config
from ingestion.embed import VectorStoreConfig
from ingestion.orchestrator import IngestionOrchestrator


def test_from_settings_maps_chunking_env_vars(monkeypatch):
    monkeypatch.setenv("CHUNKING_MAX_SIZE", "3000")
    monkeypatch.setenv("CHUNKING_MIN_SIZE", "900")
    monkeypatch.setenv("CHUNKING_MAX_WORKERS", "2")

    config = Config.from_settings()

    assert (config.max_size, config.min_size, config.max_workers) == (3000, 900, 2)


def test_from_settings_takes_model_from_embedding_settings(monkeypatch):
    monkeypatch.setenv("EMBEDDING_HUGGINGFACE_MODEL", "custom/semantic-model")

    config = Config.from_settings()

    assert config.model == "custom/semantic-model"


def test_orchestrator_default_chunking_config_honors_env(monkeypatch):
    monkeypatch.setenv("CHUNKING_MAX_SIZE", "3123")

    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(
            collection_name="test", db_url="postgresql://u:p@localhost/db"
        )
    )

    assert orchestrator.chunking_config.max_size == 3123
