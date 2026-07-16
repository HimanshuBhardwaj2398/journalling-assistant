"""Role→model resolution: explicit map + local→Groq→OpenAI fallback ladder.

Deliberately not litellm's auto-router: deterministic routing is traceable
and testable. Repoint any role with one env var (LLM_ROLE_<ROLE>).
"""

from __future__ import annotations

from typing import Literal, Optional

from config.settings import LLMSettings
from observability.langfuse import LangfuseTracer
from retrieval.llm_client import LLMClient

Role = Literal["interpreter", "grader", "answerer"]

ROLE_DEFAULTS: dict[str, str] = {
    "interpreter": "ollama/qwen3:8b",
    "grader": "ollama/qwen3:8b",
    "answerer": "groq/llama-3.3-70b-versatile",
}

# One rung per tier; fallbacks are the rungs strictly above the primary's tier.
# Off-ladder providers (e.g. anthropic/...) sit below tier 0, so they get the
# whole ladder as fallbacks, weakest rung first — pinned by test.
LADDER: list[str] = [
    "ollama/qwen3:8b",
    "groq/llama-3.3-70b-versatile",
    "openai/gpt-4o-mini",
]

_TIER = {rung.split("/", 1)[0]: tier for tier, rung in enumerate(LADDER)}


def _default_settings() -> LLMSettings:
    # provider= is unused here (models are explicit); pinning a valid value
    # keeps ambient LLM_PROVIDER from breaking role resolution (init kwargs
    # beat env in pydantic-settings; LLM_ROLE_* and ollama_base_url
    # env/aliases still resolve).
    return LLMSettings(provider="groq")


def resolve_role(
    role: Role, settings: Optional[LLMSettings] = None
) -> tuple[str, list[str]]:
    """Return (primary_model_id, fallback_model_ids) for a role.

    Raises:
        KeyError: If ``role`` is not a known role.
    """
    settings = settings or _default_settings()
    if role not in ROLE_DEFAULTS:
        raise KeyError(role)
    # No getattr default: a role added to ROLE_DEFAULTS without a matching
    # LLMSettings field must fail loudly, not silently skip its env override.
    override = getattr(settings, f"role_{role}")
    primary = override or ROLE_DEFAULTS[role]
    tier = _TIER.get(primary.split("/", 1)[0], -1)
    fallbacks = [rung for rung in LADDER if _TIER[rung.split("/", 1)[0]] > tier]
    return primary, fallbacks


def client_for_role(
    role: Role,
    settings: Optional[LLMSettings] = None,
    tracer: Optional[LangfuseTracer] = None,
) -> LLMClient:
    """Build an LLMClient carrying the role's model + escalation chain.

    Raises:
        KeyError: If ``role`` is not a known role.
    """
    settings = settings or _default_settings()
    primary, fallbacks = resolve_role(role, settings)
    return LLMClient(
        settings=settings, tracer=tracer, model_id=primary, fallback_models=fallbacks
    )
