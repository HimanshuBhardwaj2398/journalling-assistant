"""
Multi-provider LLM client for retrieval and eval pipelines.

Configure via environment variables (see config.settings.LLMSettings):
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

from typing import Optional

import litellm

from config.settings import LLMSettings
from observability.langfuse import LangfuseTracer, get_langfuse_tracer

# Suppress litellm verbose output in notebooks
litellm.suppress_debug_info = True

_PROVIDER_DEFAULTS: dict[str, str] = {
    "groq": "llama-3.3-70b-versatile",
    "ollama": "qwen2.5:7b",
    "openai": "gpt-4o-mini",
}


class LLMClient:
    """Multi-provider LLM client for retrieval and eval pipelines.

    Reads LLMSettings directly (not the cached get_settings()) so each
    construction reflects the current environment — the seam tests rely on.
    """

    def __init__(
        self,
        settings: Optional[LLMSettings] = None,
        tracer: Optional[LangfuseTracer] = None,
    ) -> None:
        settings = settings or LLMSettings()
        self.provider = settings.provider
        model = settings.model or _PROVIDER_DEFAULTS[self.provider]
        self.model_id = f"{self.provider}/{model}"
        self._tracer = tracer or get_langfuse_tracer()

        if self.provider == "ollama":
            # litellm has no per-client base URL; this is process-global state.
            litellm.api_base = settings.ollama_base_url

    def complete(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> str:
        """Call the configured LLM and return the text content."""
        with self._tracer.observe(
            name="llm.completion",
            as_type="generation",
            input=messages,
            metadata={"model_id": self.model_id},
        ) as observation:
            response = litellm.completion(
                model=self.model_id,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            text = response.choices[0].message.content.strip()

            usage = getattr(response, "usage", None)
            usage_details = None
            if usage is not None:
                usage_details = {
                    key: value
                    for key, value in (
                        ("input", getattr(usage, "prompt_tokens", None)),
                        ("output", getattr(usage, "completion_tokens", None)),
                    )
                    if value is not None
                }
            observation.update(
                output=text,
                model=self.model_id,
                model_parameters={"temperature": temperature, "max_tokens": max_tokens},
                usage_details=usage_details or None,
            )
            return text

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model_id!r})"


# Backwards-compatible alias — eval notebooks use this name
EvalLLMClient = LLMClient
