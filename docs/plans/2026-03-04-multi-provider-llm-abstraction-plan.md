# Multi-Provider LLM Abstraction Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded Groq client in the eval notebooks with a config-driven `EvalLLMClient` that can route calls to Groq, local Ollama, or OpenAI via a single `.env` variable.

**Architecture:** Add `litellm` as a dependency; create `retrieval/llm_client.py` with a thin `EvalLLMClient` class; update both eval notebooks to import and use it instead of the Groq SDK directly. Provider and model are set in `.env` — no notebook code changes needed to switch.

**Tech Stack:** LiteLLM ≥1.40.0, Ollama (local server), `qwen2.5:7b` as the local default model.

**Design doc:** `docs/plans/2026-03-04-multi-provider-llm-abstraction-design.md`

**Worktree:** `.worktrees/rag-retrieval-eval` (all paths below are relative to this worktree root)

---

## Pre-requisites

Install Ollama before starting (one-time, outside the worktree):
```bash
# Download Mac app from https://ollama.ai — or:
brew install ollama

# Pull the model (~4.5 GB, takes a few minutes)
ollama pull qwen2.5:7b

# Verify Ollama is running
curl http://localhost:11434/api/tags
```

---

### Task 1: Add `litellm` dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add litellm to pyproject.toml**

Open `pyproject.toml` and add under `[tool.poetry.dependencies]`:

```toml
litellm = ">=1.40.0,<2.0.0"
```

**Step 2: Install the new dependency**

```bash
cd .worktrees/rag-retrieval-eval
poetry add "litellm>=1.40.0,<2.0.0"
```

Expected: Resolves and installs `litellm` and its deps. Lock file updates.

**Step 3: Verify import works**

```bash
poetry run python -c "import litellm; print('litellm OK:', litellm.__version__)"
```

Expected: `litellm OK: 1.x.x`

**Step 4: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore: add litellm for multi-provider LLM abstraction"
```

---

### Task 2: Create `retrieval/llm_client.py`

**Files:**
- Create: `retrieval/llm_client.py`
- Create: `tests/retrieval/test_llm_client.py`

**Step 1: Write the failing tests first**

Create `tests/retrieval/test_llm_client.py`:

```python
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
```

**Step 2: Run tests to confirm they fail**

```bash
cd .worktrees/rag-retrieval-eval
poetry run pytest tests/retrieval/test_llm_client.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` — `retrieval.llm_client` doesn't exist yet.

**Step 3: Create `retrieval/llm_client.py`**

```python
"""
Multi-provider LLM client for eval dataset generation.

Configure via environment variables:
  LLM_PROVIDER=groq       → groq/llama-3.3-70b-versatile (default)
  LLM_PROVIDER=ollama     → ollama/qwen2.5:7b (local, requires Ollama running)
  LLM_PROVIDER=openai     → openai/gpt-4o-mini

  LLM_MODEL=<name>        → override the default model for the selected provider
  OLLAMA_BASE_URL=...     → default: http://localhost:11434

Usage:
    from retrieval.llm_client import EvalLLMClient

    client = EvalLLMClient()
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


class EvalLLMClient:
    """Thin wrapper around litellm for eval notebook LLM calls."""

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
        return f"EvalLLMClient(model={self.model_id!r})"
```

**Step 4: Run tests to confirm they pass**

```bash
poetry run pytest tests/retrieval/test_llm_client.py -v
```

Expected: All 6 tests pass.

**Step 5: Commit**

```bash
git add retrieval/llm_client.py tests/retrieval/test_llm_client.py
git commit -m "feat: add EvalLLMClient (LiteLLM-based multi-provider abstraction)"
```

---

### Task 3: Update `.env.example` with new vars

**Files:**
- Modify: `.env.example`

**Step 1: Add new vars to `.env.example`**

Find the section near `GROQ_API_KEY` and add the LLM provider config block:

```bash
# ── LLM Provider for eval notebooks ──────────────────────────────────────────
# Options: groq | ollama | openai
# Default: groq (uses GROQ_API_KEY below)
LLM_PROVIDER=ollama

# Model override (uses provider default if unset)
# groq default:   llama-3.3-70b-versatile
# ollama default: qwen2.5:7b
# openai default: gpt-4o-mini
LLM_MODEL=qwen2.5:7b

# Ollama server URL (only needed for LLM_PROVIDER=ollama)
OLLAMA_BASE_URL=http://localhost:11434

# Groq API key (only needed for LLM_PROVIDER=groq)
GROQ_API_KEY=your_groq_api_key_here
```

**Step 2: Also update your local `.env`**

In your actual `.env` file (not committed), set:
```bash
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5:7b
```

**Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: document LLM_PROVIDER env vars in .env.example"
```

---

### Task 4: Update `eval_dataset_generation.ipynb`

**Files:**
- Modify: `retrieval/eval_dataset_generation.ipynb`

The notebook has two places that use the Groq client:
1. **Import cell** — `from groq import Groq`
2. **Client init cell** — `groq_client = Groq(api_key=...)`
3. **LLM call helper** — wherever `groq_client.chat.completions.create(...)` is called

**Step 1: Update the imports cell**

Find the cell containing `from groq import Groq` and replace it with:

```python
import os
import sys
import json
import warnings
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.abspath(".."))

from dotenv import load_dotenv
load_dotenv("../.env")

import pandas as pd
from sqlalchemy import text

from db.database import session_scope
from db.crud import ChunkCRUD
from ingestion.embed import VectorStoreConfig, VectorStoreManager
from retrieval.llm_client import EvalLLMClient  # NEW: replaces groq import

print("Imports OK")
print(f"DB_URL set: {bool(os.getenv('DB_URL'))}")
print(f"VOYAGE_API_KEY set: {bool(os.getenv('VOYAGE_API_KEY'))}")

# Initialize LLM client (provider set via LLM_PROVIDER env var)
llm = EvalLLMClient()
print(f"LLM client: {llm}")
```

**Step 2: Update the QA generation function**

Find the `generate_qa_pair` function (or equivalent) that calls Groq. Replace the inner call:

**Before:**
```python
response = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.7,
    max_tokens=400,
)
raw = response.choices[0].message.content.strip()
```

**After:**
```python
raw = llm.complete(
    messages=[{"role": "user", "content": prompt}],
    temperature=0.7,
    max_tokens=400,
)
```

**Step 3: Update each of the 3 critique agent functions**

Same pattern for groundedness, standalone, and relevance critique functions:

**Before:**
```python
response = groq_client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=[{"role": "user", "content": prompt}],
    temperature=0.0,
    max_tokens=100,
)
raw = response.choices[0].message.content.strip()
```

**After:**
```python
raw = llm.complete(
    messages=[{"role": "user", "content": prompt}],
    temperature=0.0,
    max_tokens=100,
)
```

**Step 4: Smoke-test a single QA generation call**

Add a temporary test cell and run it:

```python
# Smoke test — generate one QA pair
test_chunk = all_chunks[0]["chunk_text"][:500]
result = generate_qa_pair(test_chunk)
print("Smoke test result:", json.dumps(result, indent=2))
assert "question" in result, "Expected 'question' key in output"
assert "answer" in result, "Expected 'answer' key in output"
print("✓ Smoke test passed")
```

Expected: Valid JSON with `question`, `answer`, `question_type` keys.

**Step 5: Commit**

```bash
git add retrieval/eval_dataset_generation.ipynb
git commit -m "feat: swap Groq client for EvalLLMClient in eval_dataset_generation notebook"
```

---

### Task 5: Update `rag_retrieval_eval.ipynb`

**Files:**
- Modify: `retrieval/rag_retrieval_eval.ipynb`

Same pattern as Task 4 — the notebook has one Groq usage: the `judge_relevance` function.

**Step 1: Update the imports cell**

Replace `from groq import Groq` with:

```python
from retrieval.llm_client import EvalLLMClient

llm = EvalLLMClient()
print(f"LLM judge: {llm}")
```

**Step 2: Update `judge_relevance` function**

**Before:**
```python
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def judge_relevance(query: str, chunk_text: str) -> dict:
    prompt = JUDGE_PROMPT.format(query=query, chunk_text=chunk_text[:800])
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100,
        )
        raw = response.choices[0].message.content.strip()
        return json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        print(f"  Judge error: {e}")
        return {"score": -1, "reason": "error"}
```

**After:**
```python
def judge_relevance(query: str, chunk_text: str) -> dict:
    prompt = JUDGE_PROMPT.format(query=query, chunk_text=chunk_text[:800])
    try:
        raw = llm.complete(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=100,
        )
        return json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        print(f"  Judge error: {e}")
        return {"score": -1, "reason": "error"}
```

**Step 3: Smoke-test the judge**

```python
# Test judge on one pair
sample_score = judge_relevance(TEST_QUERIES[0], all_results[0]["chunk_text"])
print(f"Sample judge output: {sample_score}")
assert "score" in sample_score, "Expected 'score' key"
assert 1 <= sample_score.get("score", 0) <= 5, "Expected score 1-5"
print("✓ Judge smoke test passed")
```

**Step 4: Commit**

```bash
git add retrieval/rag_retrieval_eval.ipynb
git commit -m "feat: swap Groq client for EvalLLMClient in rag_retrieval_eval notebook"
```

---

### Task 6: End-to-end verification

**Step 1: Confirm Ollama is running with the model**

```bash
# In a terminal, start Ollama (if not already running as a service)
ollama serve

# In another terminal, confirm the model is available
ollama list
# Expected: qwen2.5:7b listed
```

**Step 2: Set env and run a single notebook cell**

In `eval_dataset_generation.ipynb`:
1. Set `LLM_PROVIDER=ollama` in `.env`
2. Restart kernel
3. Run the imports cell → should print `LLM client: EvalLLMClient(model='ollama/qwen2.5:7b')`
4. Run the smoke test cell → should return valid JSON

**Step 3: Switch back to Groq to verify provider switching**

1. Set `LLM_PROVIDER=groq` in `.env`
2. Restart kernel
3. Run imports cell → should print `LLM client: EvalLLMClient(model='groq/llama-3.3-70b-versatile')`
4. Run the smoke test cell → should return valid JSON (requires `GROQ_API_KEY` set)

**Step 4: Run the full test suite**

```bash
cd .worktrees/rag-retrieval-eval
poetry run pytest tests/ -v --tb=short
```

Expected: All tests pass including `tests/retrieval/test_llm_client.py`.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat: multi-provider LLM abstraction complete — Groq/Ollama/OpenAI switchable via .env"
```

---

## Notes

### Rate limits removed for local Ollama

The eval notebooks have `time.sleep(2.1)` calls between Groq API calls (free tier rate limit). When using Ollama locally, you can remove or reduce these sleeps. Add a cell at the top:

```python
INTER_CALL_DELAY = 0.0 if os.getenv("LLM_PROVIDER") == "ollama" else 2.1
```

### Model quality vs speed tradeoff

If `qwen2.5:7b` is too slow (15 tok/s → ~800 calls takes 60-90 min):
```bash
# In .env
LLM_MODEL=phi4-mini   # 3.8B, ~30 tok/s, still good JSON output
```

### JSON parse failures with smaller local models

If you see `JSONDecodeError` frequently with a smaller local model, it's producing malformed JSON. The existing `try/except` in both notebooks handles this gracefully (sets score to -1). But if error rate > 10%, switch to `qwen2.5:7b` which is the most reliable for JSON at ≤7B size.

### Tracking better models

Check these when planning future runs:
- [HuggingFace Open LLM Leaderboard](https://huggingface.co/spaces/open-llm-leaderboard/open_llm_leaderboard)
- [LMSYS Chatbot Arena](https://huggingface.co/spaces/lmarena-ai/arena-leaderboard)
- [r/LocalLLaMA](https://reddit.com/r/LocalLLaMA)
