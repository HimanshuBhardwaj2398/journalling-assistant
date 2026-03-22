"""Tests for settings compatibility behaviors."""

from config.settings import Settings


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
