"""Role→model resolution: explicit map + local→Groq→OpenAI fallback ladder.

Deliberately not litellm's auto-router: deterministic routing is traceable
and testable. Repoint any role with one env var (LLM_ROLE_<ROLE>).
"""

from __future__ import annotations

from typing import Optional

from config.settings import LLMSettings
from observability.langfuse import LangfuseTracer
from retrieval.llm_client import LLMClient

ROLE_DEFAULTS: dict[str, str] = {
    "interpreter": "ollama/qwen3:8b",
    "grader": "ollama/qwen3:8b",
    "answerer": "groq/llama-3.3-70b-versatile",
}

# One rung per tier; fallbacks are the rungs strictly above the primary's tier.
LADDER: list[str] = [
    "ollama/qwen3:8b",
    "groq/llama-3.3-70b-versatile",
    "openai/gpt-4o-mini",
]

_TIER = {"ollama": 0, "groq": 1, "openai": 2}


def resolve_role(
    role: str, settings: Optional[LLMSettings] = None
) -> tuple[str, list[str]]:
    """Return (primary_model_id, fallback_model_ids) for a role."""
    # provider= is unused here (models are explicit); pinning a valid value
    # keeps ambient LLM_PROVIDER from breaking role resolution (init kwargs
    # beat env in pydantic-settings; LLM_ROLE_* and ollama_base_url
    # env/aliases still resolve).
    settings = settings or LLMSettings(provider="groq")
    override = getattr(settings, f"role_{role}", None)
    primary = override or ROLE_DEFAULTS[role]  # KeyError on unknown role
    tier = _TIER.get(primary.split("/", 1)[0], -1)
    fallbacks = [
        rung
        for rung in LADDER
        if rung != primary and _TIER[rung.split("/", 1)[0]] > tier
    ]
    return primary, fallbacks


def client_for_role(
    role: str,
    settings: Optional[LLMSettings] = None,
    tracer: Optional[LangfuseTracer] = None,
) -> LLMClient:
    """Build an LLMClient carrying the role's model + escalation chain."""
    # Same env-independence rationale as resolve_role: provider is unused on
    # the explicit-model path, so pin a valid value.
    settings = settings or LLMSettings(provider="groq")
    primary, fallbacks = resolve_role(role, settings)
    return LLMClient(
        settings=settings, tracer=tracer, model_id=primary, fallback_models=fallbacks
    )
