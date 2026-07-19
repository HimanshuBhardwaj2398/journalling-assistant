"""Tests for role→model resolution and the fallback ladder."""

import pytest


def test_default_roles(monkeypatch):
    for var in ("LLM_ROLE_INTERPRETER", "LLM_ROLE_GRADER", "LLM_ROLE_ANSWERER"):
        monkeypatch.delenv(var, raising=False)
    from agent.router import resolve_role

    model, fallbacks = resolve_role("interpreter")
    assert model == "ollama/qwen3:8b"
    assert fallbacks == ["groq/llama-3.3-70b-versatile", "openai/gpt-4o-mini"]

    model, fallbacks = resolve_role("answerer")
    assert model == "groq/llama-3.3-70b-versatile"
    assert fallbacks == ["openai/gpt-4o-mini"]


def test_env_override(monkeypatch):
    monkeypatch.setenv("LLM_ROLE_GRADER", "groq/llama-3.1-8b-instant")
    from agent.router import resolve_role

    model, fallbacks = resolve_role("grader")
    assert model == "groq/llama-3.1-8b-instant"
    assert fallbacks == ["openai/gpt-4o-mini"]  # only rungs above groq tier


def test_openai_primary_has_no_fallbacks(monkeypatch):
    monkeypatch.setenv("LLM_ROLE_ANSWERER", "openai/gpt-4o")
    from agent.router import resolve_role

    model, fallbacks = resolve_role("answerer")
    assert model == "openai/gpt-4o"
    assert fallbacks == []


def test_unknown_role_raises(monkeypatch):
    from agent.router import resolve_role

    with pytest.raises(KeyError):
        resolve_role("poet")


def test_malformed_role_override_rejected_at_settings_construction(monkeypatch):
    # Forgot the provider prefix: must fail loudly at construction, not map to
    # tier -1 and get silently served by the weakest ladder rung at request time.
    monkeypatch.setenv("LLM_ROLE_ANSWERER", "llama-3.3-70b-versatile")
    from pydantic import ValidationError

    from config.settings import LLMSettings

    with pytest.raises(ValidationError, match="provider/model"):
        LLMSettings(provider="groq")


def test_off_ladder_provider_gets_whole_ladder_as_fallbacks(monkeypatch):
    # Pinned behavior: off-ladder providers sit below tier 0, so every rung
    # (weakest first) becomes a fallback.
    monkeypatch.setenv("LLM_ROLE_GRADER", "anthropic/claude-haiku")
    from agent.router import LADDER, resolve_role

    model, fallbacks = resolve_role("grader")
    assert model == "anthropic/claude-haiku"
    assert fallbacks == LADDER


def test_client_for_role_wires_chain(monkeypatch):
    for var in ("LLM_ROLE_INTERPRETER", "LLM_ROLE_GRADER", "LLM_ROLE_ANSWERER"):
        monkeypatch.delenv(var, raising=False)
    from agent.router import client_for_role

    client = client_for_role("interpreter")
    assert client.model_id == "ollama/qwen3:8b"
    assert client.fallback_models == ["groq/llama-3.3-70b-versatile", "openai/gpt-4o-mini"]


def test_bogus_env_provider_does_not_break_role_resolution(monkeypatch):
    # Regression (Task 3 review trail): bare LLMSettings() validates ambient
    # LLM_PROVIDER even though provider is unused on explicit-model paths.
    # Role resolution must stay env-independent.
    monkeypatch.setenv("LLM_PROVIDER", "bogus")
    for var in ("LLM_ROLE_INTERPRETER", "LLM_ROLE_GRADER", "LLM_ROLE_ANSWERER"):
        monkeypatch.delenv(var, raising=False)
    from agent.router import client_for_role

    client = client_for_role("interpreter")
    assert client.model_id == "ollama/qwen3:8b"
    assert client.fallback_models == ["groq/llama-3.3-70b-versatile", "openai/gpt-4o-mini"]
