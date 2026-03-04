"""Tests for EvalLLMClient — runs in offline mode using litellm mock."""
import os
import pytest
from unittest.mock import patch, MagicMock


def make_mock_response(content: str):
    """Build a litellm-shaped mock response."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestEvalLLMClientInit:
    def test_defaults_to_groq(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from retrieval.llm_client import EvalLLMClient
        client = EvalLLMClient()
        assert client.model_id == "groq/llama-3.3-70b-versatile"

    def test_ollama_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from retrieval.llm_client import EvalLLMClient
        client = EvalLLMClient()
        assert client.model_id == "ollama/qwen2.5:7b"

    def test_openai_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from retrieval.llm_client import EvalLLMClient
        client = EvalLLMClient()
        assert client.model_id == "openai/gpt-4o-mini"

    def test_model_override(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("LLM_MODEL", "phi4-mini")
        from retrieval.llm_client import EvalLLMClient
        client = EvalLLMClient()
        assert client.model_id == "ollama/phi4-mini"

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "unknown_provider")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from retrieval.llm_client import EvalLLMClient
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            EvalLLMClient()


class TestEvalLLMClientComplete:
    def test_complete_returns_string(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        from retrieval.llm_client import EvalLLMClient
        import litellm
        with patch.object(litellm, "completion", return_value=make_mock_response('{"score": 4}')):
            client = EvalLLMClient()
            result = client.complete(messages=[{"role": "user", "content": "test"}])
        assert result == '{"score": 4}'

    def test_complete_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        from retrieval.llm_client import EvalLLMClient
        import litellm
        with patch.object(litellm, "completion", return_value=make_mock_response("  hello  \n")):
            client = EvalLLMClient()
            result = client.complete(messages=[{"role": "user", "content": "test"}])
        assert result == "hello"
