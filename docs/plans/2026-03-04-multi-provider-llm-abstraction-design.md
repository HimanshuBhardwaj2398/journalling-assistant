# Design: Multi-Provider LLM Abstraction for Eval Notebooks

**Date**: 2026-03-04
**Status**: Approved
**Author**: Chetna (via Claude Code brainstorming session)

---

## Problem

The eval dataset generation pipeline (`eval_dataset_generation.ipynb`) and retrieval eval (`rag_retrieval_eval.ipynb`) are hardcoded to the **Groq API** (`llama-3.3-70b-versatile`). The Groq free tier (100K tokens/day, 30 req/min) is insufficient for a full eval run (~800 API calls, ~90K tokens). Hitting the daily limit blocks all eval work.

## Goal

Add a config-driven LLM abstraction that lets any of these providers be used interchangeably with a single `.env` change — no code modifications needed to switch between Groq, a local Ollama model, or OpenAI.

---

## Solution: LiteLLM + EvalLLMClient

### Why LiteLLM

[LiteLLM](https://github.com/BerriAI/litellm) is a Python SDK that unifies 100+ LLM providers under the OpenAI completion interface:

```python
litellm.completion(model="groq/llama-3.3-70b-versatile", ...)  # cloud Groq
litellm.completion(model="ollama/qwen2.5:7b", ...)             # local Ollama
litellm.completion(model="openai/gpt-4o-mini", ...)            # OpenAI
```

Chosen over alternatives:
- **Custom thin wrapper**: LiteLLM already handles provider-specific auth, retries, error normalization
- **Raw Ollama SDK**: Works only for Ollama; LiteLLM works for all 3 target providers
- **AnythingLLM**: Desktop GUI app, not a Python library — not suitable for batch eval notebook use

### Why NOT AnythingLLM

AnythingLLM is an end-user desktop RAG application (similar to what this project is building). It has its own document management, vector store, and chat UI. It exposes a REST API but is designed for interactive chat, not programmatic batch generation loops. Using it would add an external server dependency with higher complexity than LiteLLM.

---

## Architecture

```
retrieval/
  llm_client.py               # NEW: EvalLLMClient wrapping LiteLLM
  eval_dataset_generation.ipynb   # UPDATED: import EvalLLMClient
  rag_retrieval_eval.ipynb        # UPDATED: swap Groq judge → EvalLLMClient

.env                              # UPDATED: LLM_PROVIDER, LLM_MODEL vars
.env.example                      # UPDATED: document new vars
pyproject.toml                    # UPDATED: add litellm dependency
```

### `retrieval/llm_client.py`

```python
import os
import litellm
from typing import Optional

class EvalLLMClient:
    """Config-driven LLM client for eval generation.

    Provider selection via .env:
      LLM_PROVIDER=groq       → groq/llama-3.3-70b-versatile
      LLM_PROVIDER=ollama     → ollama/qwen2.5:7b (local, http://localhost:11434)
      LLM_PROVIDER=openai     → openai/gpt-4o-mini

    Override model: LLM_MODEL=<model-name>
    """

    PROVIDER_DEFAULTS = {
        "groq": "llama-3.3-70b-versatile",
        "ollama": "qwen2.5:7b",
        "openai": "gpt-4o-mini",
    }

    def __init__(self):
        provider = os.getenv("LLM_PROVIDER", "groq").lower()
        model = os.getenv("LLM_MODEL", self.PROVIDER_DEFAULTS[provider])
        self.model_id = f"{provider}/{model}"

        # Ollama: point to local server
        if provider == "ollama":
            litellm.api_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def complete(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 200,
    ) -> str:
        response = litellm.completion(
            model=self.model_id,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
```

### `.env` additions

```bash
# LLM provider for eval dataset generation
# Options: groq | ollama | openai
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b          # optional override; uses provider default if unset
OLLAMA_BASE_URL=http://localhost:11434  # optional; this is the default
```

### Notebook changes (both notebooks)

**Before:**
```python
from groq import Groq
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

response = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[...],
    temperature=0.0,
    max_tokens=200,
)
raw = response.choices[0].message.content.strip()
```

**After:**
```python
from retrieval.llm_client import EvalLLMClient
client = EvalLLMClient()

raw = client.complete(messages=[...], temperature=0.0, max_tokens=200)
```

---

## Local LLM Setup (Ollama on M1 Air 8GB)

### Why qwen2.5:7b

Based on [StructEval benchmark](https://arxiv.org/html/2505.20139v1) and [Berkeley Function-Calling Leaderboard](https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard), `qwen2.5:7b` is the top performer for structured JSON output at ≤7B parameters — critical for the critique agents that must return `{"score": int, "reason": str}`.

| Model | Disk size (Q4) | JSON reliability | Speed on 8GB M1 |
|-------|---------------|-----------------|-----------------|
| `qwen2.5:7b` | ~4.5 GB | ⭐⭐⭐⭐⭐ | ~15 tok/s |
| `phi4-mini` (3.8B) | ~2.3 GB | ⭐⭐⭐⭐ | ~30 tok/s |
| `mistral:7b` | ~4.1 GB | ⭐⭐⭐ | ~18 tok/s |

**Recommendation**: `qwen2.5:7b` as the default. Switch to `phi4-mini` via `LLM_MODEL=phi4-mini` if 15 tok/s is too slow for a full 800-call run.

### Ollama installation

```bash
# 1. Install Ollama (from https://ollama.ai — download the Mac app)
# 2. Pull model
ollama pull qwen2.5:7b      # ~4.5 GB, one-time download

# 3. Ollama starts automatically on Mac (or: ollama serve)
# 4. Verify
curl http://localhost:11434/api/tags
```

---

## Tracking Model Quality

Bookmark these to stay current with best local models:

| Resource | URL | Use for |
|----------|-----|---------|
| HuggingFace Open LLM Leaderboard | [link](https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard) | Benchmark scores |
| LMSYS Chatbot Arena | [link](https://huggingface.co/spaces/lmarena-ai/arena-leaderboard) | Human preference |
| llm-stats.com | [link](https://llm-stats.com) | All leaderboards aggregated |
| r/LocalLLaMA | [link](https://reddit.com/r/LocalLLaMA) | Community M1 performance reports |

---

## Verification

1. `LLM_PROVIDER=ollama ollama serve` → notebook cell 1 prints `EvalLLMClient using ollama/qwen2.5:7b`
2. Single QA generation call returns valid JSON `{"question": ..., "answer": ..., "question_type": ...}`
3. Single critique call returns valid JSON `{"score": 4, "reason": "..."}`
4. Full eval run completes with < 5% JSON parse errors
5. Switch to `LLM_PROVIDER=groq` → same notebooks work without code changes
