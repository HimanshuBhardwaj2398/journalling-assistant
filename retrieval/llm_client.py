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

    # Environment-driven (default):
    client = LLMClient()
    text = client.complete(messages=[{"role": "user", "content": "..."}])

    # Explicit model with a fallback chain (escalates a rung on any error):
    client = LLMClient(
        model_id="ollama/qwen3:8b",
        fallback_models=["groq/llama-3.3-70b-versatile"],
    )

For ollama models, `api_base` is passed per call (never set globally on
litellm) so mixed-provider fallback chains do not poison each other.
"""

import logging
from typing import Optional

import litellm

from config.settings import LLMSettings
from observability.langfuse import LangfuseTracer, get_langfuse_tracer

logger = logging.getLogger(__name__)

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
        model_id: Optional[str] = None,
        fallback_models: Optional[list[str]] = None,
    ) -> None:
        settings = settings or LLMSettings()
        if model_id is None:
            self.provider = settings.provider
            model = settings.model or _PROVIDER_DEFAULTS[self.provider]
            self.model_id = f"{self.provider}/{model}"
        else:
            self.model_id = model_id
            self.provider = model_id.split("/", 1)[0]
        self.fallback_models = list(fallback_models or [])
        self._ollama_base_url = settings.ollama_base_url
        self._tracer = tracer or get_langfuse_tracer()

    def _api_base_for(self, model: str) -> Optional[str]:
        # api_base is per-call: a global litellm.api_base would poison the
        # non-ollama rungs of a mixed fallback chain.
        return self._ollama_base_url if model.startswith("ollama/") else None

    def complete(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> str:
        """Call the model chain, escalating a tier on any error."""
        chain = [self.model_id, *self.fallback_models]
        with self._tracer.observe(
            name="llm.completion",
            as_type="generation",
            input=messages,
            metadata={"model_chain": chain},
        ) as observation:
            last_exc: Optional[Exception] = None
            for index, model in enumerate(chain):
                try:
                    response = litellm.completion(
                        model=model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        api_base=self._api_base_for(model),
                    )
                except Exception as exc:
                    last_exc = exc
                    logger.warning("LLM %s failed (%s); escalating", model, exc)
                    continue

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
                    model=model,
                    model_parameters={"temperature": temperature, "max_tokens": max_tokens},
                    usage_details=usage_details or None,
                    metadata={"served_by": model, "escalations": index},
                )
                return text
            assert last_exc is not None  # chain always has >= 1 rung
            raise last_exc

    def __repr__(self) -> str:
        return f"LLMClient(model={self.model_id!r})"


# Backwards-compatible alias — eval notebooks use this name
EvalLLMClient = LLMClient
