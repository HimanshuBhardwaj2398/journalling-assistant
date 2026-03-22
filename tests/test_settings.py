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
