"""Tests for EvalLLMClient — runs in offline mode using litellm mock."""

from unittest.mock import MagicMock, patch

import pytest


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
        import litellm

        from retrieval.llm_client import EvalLLMClient

        with patch.object(litellm, "completion", return_value=make_mock_response('{"score": 4}')):
            client = EvalLLMClient()
            result = client.complete(messages=[{"role": "user", "content": "test"}])
        assert result == '{"score": 4}'

    def test_complete_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        import litellm

        from retrieval.llm_client import EvalLLMClient

        with patch.object(litellm, "completion", return_value=make_mock_response("  hello  \n")):
            client = EvalLLMClient()
            result = client.complete(messages=[{"role": "user", "content": "test"}])
        assert result == "hello"


class TestLLMClientFallbackChain:
    def test_explicit_model_id_overrides_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        from retrieval.llm_client import LLMClient

        client = LLMClient(model_id="ollama/qwen3:8b")
        assert client.model_id == "ollama/qwen3:8b"
        assert client.provider == "ollama"

    def test_fallback_escalates_on_error(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        import litellm

        from retrieval.llm_client import LLMClient

        calls = []

        def flaky_completion(**kwargs):
            calls.append(kwargs["model"])
            if kwargs["model"].startswith("ollama/"):
                raise RuntimeError("connection refused")
            return make_mock_response("ok")

        with patch.object(litellm, "completion", side_effect=flaky_completion):
            client = LLMClient(
                model_id="ollama/qwen3:8b",
                fallback_models=["groq/llama-3.3-70b-versatile"],
            )
            result = client.complete(messages=[{"role": "user", "content": "hi"}])

        assert result == "ok"
        assert calls == ["ollama/qwen3:8b", "groq/llama-3.3-70b-versatile"]

    def test_all_rungs_fail_raises_last_error(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        import litellm

        from retrieval.llm_client import LLMClient

        def failing_completion(**kwargs):
            if kwargs["model"].startswith("ollama/"):
                raise RuntimeError("ollama connection refused")
            raise RuntimeError("groq rate limited")

        with patch.object(litellm, "completion", side_effect=failing_completion):
            client = LLMClient(model_id="ollama/qwen3:8b", fallback_models=["groq/x"])
            with pytest.raises(RuntimeError, match="groq rate limited"):
                client.complete(messages=[{"role": "user", "content": "hi"}])

    def test_ollama_api_base_passed_per_call_only(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_OLLAMA_BASE_URL", raising=False)
        import litellm

        from retrieval.llm_client import LLMClient

        seen = []

        def record_completion(**kwargs):
            seen.append((kwargs["model"], kwargs.get("api_base")))
            if kwargs["model"].startswith("ollama/"):
                raise RuntimeError("down")
            return make_mock_response("ok")

        with patch.object(litellm, "completion", side_effect=record_completion):
            client = LLMClient(model_id="ollama/qwen3:8b", fallback_models=["groq/x"])
            client.complete(messages=[{"role": "user", "content": "hi"}])

        # ollama call carries the default base URL; groq call must NOT
        assert seen[0] == ("ollama/qwen3:8b", "http://localhost:11434")
        assert seen[1][1] is None
        # the global litellm state must never be touched
        assert litellm.api_base is None

    def test_explicit_chain_ignores_bogus_env_provider(self, monkeypatch):
        # Ambient LLM_PROVIDER must not poison env-independent explicit chains.
        monkeypatch.setenv("LLM_PROVIDER", "bogus")
        import litellm

        from retrieval.llm_client import LLMClient

        with patch.object(litellm, "completion", return_value=make_mock_response("ok")):
            client = LLMClient(model_id="ollama/qwen3:8b")
            result = client.complete(messages=[{"role": "user", "content": "hi"}])

        assert client.model_id == "ollama/qwen3:8b"
        assert client.provider == "ollama"
        assert result == "ok"

    def test_empty_content_escalates_to_next_rung(self, monkeypatch):
        # A rung answering with None content (e.g. reasoning burning the whole
        # max_tokens budget) must escalate, not crash on None.strip().
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        import litellm

        from retrieval.llm_client import LLMClient

        with patch.object(
            litellm,
            "completion",
            side_effect=[make_mock_response(None), make_mock_response("ok")],
        ):
            client = LLMClient(model_id="ollama/qwen3:8b", fallback_models=["groq/x"])
            result = client.complete(messages=[{"role": "user", "content": "hi"}])

        assert result == "ok"

    def test_total_failure_records_error_on_span(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        from contextlib import contextmanager

        import litellm

        from retrieval.llm_client import LLMClient

        updates = []

        class FakeObservation:
            def update(self, **kwargs):
                updates.append(kwargs)

        class FakeTracer:
            @contextmanager
            def observe(self, **kwargs):
                yield FakeObservation()

        with patch.object(litellm, "completion", side_effect=RuntimeError("down")):
            client = LLMClient(
                model_id="ollama/qwen3:8b",
                fallback_models=["groq/x"],
                tracer=FakeTracer(),
            )
            with pytest.raises(RuntimeError, match="down"):
                client.complete(messages=[{"role": "user", "content": "hi"}])

        error_updates = [u for u in updates if u.get("level") == "ERROR"]
        assert len(error_updates) == 1
        assert "down" in error_updates[0]["status_message"]
        assert error_updates[0]["metadata"] == {"escalations": 2}
