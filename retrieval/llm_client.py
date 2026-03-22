"""
Multi-provider LLM client for retrieval and eval pipelines.

Configure via environment variables:
  LLM_PROVIDER=groq       → groq/llama-3.3-70b-versatile (default)
  LLM_PROVIDER=ollama     → ollama/qwen2.5:7b (local, requires Ollama running)
  LLM_PROVIDER=openai     → openai/gpt-4o-mini

  LLM_MODEL=<name>        → override the default model for the selected provider
  OLLAMA_BASE_URL=...     → default: http://localhost:11434

Usage:
    from retrieval.llm_client import LLMClient

    client = LLMClient()
    text = client.complete(messages=[{"role": "user", "content": "..."}])
"""

import os
import litellm

# Suppress litellm verbose output in notebooks
litellm.suppress_debug_info = True

_PROVIDER_DEFAULTS: dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "ollama": "qwen2.5:7b",
    "openai": "gpt-4o-mini",
}


class LLMClient:
    """Multi-provider LLM client for retrieval and eval pipelines."""

    def __init__(self) -> None:
        provider = os.getenv("LLM_PROVIDER", "groq").lower().strip()
        if provider not in _PROVIDER_DEFAULTS:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{provider}'. "
                f"Must be one of: {list(_PROVIDER_DEFAULTS)}"
            )
        model = os.getenv("LLM_MODEL", _PROVIDER_DEFAULTS[provider]).strip()
        self.model_id = f"{provider}/{model}"
        self.provider = provider

        if provider == "ollama":
            litellm.api_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def complete(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> str:
        """Call the configured LLM and return the text content."""
        response = litellm.completion(
            model=self.model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model_id!r})"


# Backwards-compatible alias — eval notebooks use this name
EvalLLMClient = LLMClient
