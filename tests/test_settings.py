"""Tests for settings compatibility behaviors."""

import pytest

from config.settings import ChunkingSettings, DatabaseSettings, Settings


def test_chunking_settings_enforce_max_greater_than_min_when_built_directly():
    """The invariant must live on ChunkingSettings itself, not only on the parent."""
    with pytest.raises(ValueError):
        ChunkingSettings(max_size=100, min_size=200)


def test_db_url_native_env_name_still_works(monkeypatch):
    """Guard for the AliasChoices swap: DB_URL (the prefixed name) must keep working."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_URL", "postgresql://u:p@localhost/native")

    settings = DatabaseSettings()

    assert settings.url == "postgresql://u:p@localhost/native"


def test_settings_accepts_release_as_debug_false(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    monkeypatch.setenv("DEBUG", "release")
    settings = Settings()

    assert settings.debug is False


def test_settings_accepts_development_as_debug_true(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    monkeypatch.setenv("DEBUG", "development")
    settings = Settings()

    assert settings.debug is True


def test_langfuse_settings_detect_when_configured(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-demo")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-demo")
    settings = Settings()

    assert settings.langfuse.is_configured is True


def test_vector_collection_name_defaults_to_buddhist_texts(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    settings = Settings()

    assert settings.vector.collection_name == "buddhist_texts"


def test_is_remote_true_for_neon_host():
    """Neon (managed Postgres) must be treated as remote: needs TLS + resilient pooling."""
    settings = DatabaseSettings(
        url="postgresql://u:p@ep-cool-name-123456-pooler.ap-south-1.aws.neon.tech/neondb?sslmode=require"
    )

    assert settings.is_remote is True


def test_is_remote_true_for_supabase_host():
    """Any cloud host counts as remote, not just Neon."""
    settings = DatabaseSettings(
        url="postgresql://u:p@aws-1-ap-south-1.pooler.supabase.com:5432/postgres"
    )

    assert settings.is_remote is True


def test_is_remote_false_for_localhost():
    """Local dev databases stay on the plain (no-SSL) connection path."""
    settings = DatabaseSettings(url="postgresql://u:p@localhost:5432/journalling_dev")

    assert settings.is_remote is False
