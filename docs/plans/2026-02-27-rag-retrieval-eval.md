# RAG Retrieval Quality Evaluation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build `experiments/rag_retrieval_eval.ipynb` — a Jupyter notebook that evaluates 4 retrieval strategies (Top-K, MMR, Score Threshold, Hybrid BM25+Semantic) against the meditation corpus and scores results with a Groq LLM judge.

**Architecture:** Load chunk texts from PostgreSQL `chunks` table into a BM25 in-memory index; connect to existing LangChain PGVector store; run 10 test queries through all 4 strategies; collect similarity scores + chunk text; send each to Groq (`llama-3.3-70b-versatile`) for 1–5 relevance scoring; summarise results in a pandas comparison table.

**Tech Stack:** LangChain PGVector (`langchain_community`), `rank-bm25`, `langchain` EnsembleRetriever, Groq SDK (OpenAI-compatible), pandas, SQLAlchemy, Voyage AI embeddings

**Design doc:** `docs/plans/2026-02-27-rag-retrieval-eval-design.md`

---

## Task 1: Add missing dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add rank-bm25 and groq to pyproject.toml**

In the `[tool.poetry.dependencies]` section, add:

```toml
rank-bm25 = ">=0.2.2,<1.0.0"
groq = ">=0.9.0,<1.0.0"
```

**Step 2: Install dependencies**

```bash
poetry add rank-bm25 groq
```

Expected: Both packages install without conflicts. `poetry.lock` is updated.

**Step 3: Verify imports work**

```bash
poetry run python -c "import rank_bm25; import groq; print('OK')"
```

Expected: `OK`

**Step 4: Add GROQ_API_KEY to .env.example**

Open `.env.example` and add at the bottom:

```
# Groq API (for LLM-as-judge in evaluation experiments)
GROQ_API_KEY=your_groq_api_key_here
```

Get a free key at: https://console.groq.com

**Step 5: Add GROQ_API_KEY to your .env file** (not committed)

**Step 6: Commit**

```bash
git add pyproject.toml poetry.lock .env.example
git commit -m "feat: add rank-bm25 and groq dependencies for retrieval eval"
```

---

## Task 2: Create notebook with Setup cell

**Files:**
- Create: `experiments/rag_retrieval_eval.ipynb`

**Step 1: Create the notebook**

```bash
poetry run jupyter notebook experiments/rag_retrieval_eval.ipynb
```

Or create it manually — add Cell 1 as a **Markdown** cell:

```markdown
# RAG Retrieval Quality Evaluation

Compares 4 retrieval strategies against the meditation corpus (Pali Canon):
1. **Top-K similarity** — dense vector search, pure semantic relevance
2. **MMR** — Maximal Marginal Relevance, reduces redundant results
3. **Score threshold** — returns only chunks above a similarity cutoff
4. **Hybrid (BM25 + Semantic)** — sparse keyword + dense vector via EnsembleRetriever

**LLM Judge:** Groq `llama-3.3-70b-versatile` scores each retrieved chunk 1–5 for relevance.
```

**Step 2: Add Cell 2 — Imports and environment (code cell)**

```python
import os
import sys
import json
import warnings
warnings.filterwarnings("ignore")

# Add project root to path so we can import project modules
sys.path.insert(0, os.path.abspath(".."))

from dotenv import load_dotenv
load_dotenv("../.env")

import pandas as pd
from groq import Groq
from sqlalchemy import text

from db.database import session_scope
from db.crud import ChunkCRUD
from ingestion.embed import VectorStoreConfig, VectorStoreManager
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain_core.documents import Document

print("Imports OK")
print(f"DB_URL set: {bool(os.getenv('DB_URL'))}")
print(f"VOYAGE_API_KEY set: {bool(os.getenv('VOYAGE_API_KEY'))}")
print(f"GROQ_API_KEY set: {bool(os.getenv('GROQ_API_KEY'))}")
```

Expected output:
```
Imports OK
DB_URL set: True
VOYAGE_API_KEY set: True
GROQ_API_KEY set: True
```

**Step 3: Run Cell 2 and verify all 3 keys show True**

If any show `False`, check your `.env` file before continuing.

---

## Task 3: Load chunks from DB and build BM25 index

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 3 — Load all chunks (code cell)**

```python
# Load all chunk texts + metadata from the chunks table
all_chunks = []

with session_scope() as session:
    result = session.execute(
        text("SELECT uuid, chunk_text, chunk_metadata, document_id FROM chunks ORDER BY document_id, chunk_index")
    )
    rows = result.fetchall()
    for row in rows:
        all_chunks.append({
            "uuid": row[0],
            "chunk_text": row[1],
            "chunk_metadata": row[2] or {},
            "document_id": row[3],
        })

print(f"Loaded {len(all_chunks)} chunks from database")
print(f"\nSample chunk (first 200 chars):")
print(all_chunks[0]["chunk_text"][:200])
```

Expected: `Loaded N chunks from database` where N > 0, plus a sample chunk preview.

**Step 2: Add Cell 4 — Build BM25Retriever (code cell)**

```python
# Build LangChain Documents for BM25
lc_documents = [
    Document(
        page_content=c["chunk_text"],
        metadata={**c["chunk_metadata"], "uuid": c["uuid"], "document_id": c["document_id"]}
    )
    for c in all_chunks
]

# Build BM25 retriever from chunk texts
bm25_retriever = BM25Retriever.from_documents(lc_documents, k=5)

print(f"BM25 index built with {len(lc_documents)} documents")
```

Expected: `BM25 index built with N documents`

**Step 3: Run both cells and verify output**

---

## Task 4: Connect to PGVector store

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 5 — Connect PGVector (code cell)**

```python
# Connect to the existing PGVector collection using project's VectorStoreManager
config = VectorStoreConfig(
    model_name="voyage-3.5",
    collection_name="documents",   # matches ingestion pipeline default
    db_url=os.getenv("DB_URL"),
)

vsm = VectorStoreManager(config)
vector_store = vsm.vector_store  # triggers lazy connection

print(f"Connected to PGVector collection: {config.collection_name}")
print(f"Collection info: {vsm.get_collection_info()}")
```

Expected:
```
Connected to PGVector collection: documents
Collection info: {'collection_name': 'documents', 'model_name': 'voyage-3.5', ...}
```

**Step 2: Add Cell 6 — Quick sanity search (code cell)**

```python
# Sanity check: run one similarity search to confirm the store works
test_results = vector_store.similarity_search_with_score("what is mindfulness", k=3)
print(f"Sanity check: retrieved {len(test_results)} results")
for doc, score in test_results:
    print(f"  Score: {score:.4f} | {doc.page_content[:80]}...")
```

Expected: 3 results with scores printed. If you get an error, check your `DB_URL` and that embeddings exist in the DB.

---

## Task 5: Define test queries and run Strategy 1 — Top-K similarity

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 7 — Test query set (code cell)**

```python
TEST_QUERIES = [
    # Conceptual
    "What is the nature of impermanence?",
    "How does craving lead to suffering?",
    "What is the relationship between mind and consciousness?",
    # Practice
    "How to establish mindfulness of breathing?",
    "What are the factors of the noble eightfold path?",
    "How does one develop concentration in meditation?",
    # Pali-specific
    "What does anicca mean?",
    "Explain the jhanas and their qualities",
    # Cross-document
    "What does the Buddha say about loving-kindness?",
    "How is equanimity described across the discourses?",
]

print(f"Test query set: {len(TEST_QUERIES)} queries")
```

**Step 2: Add Cell 8 — Strategy 1: Top-K similarity (code cell)**

```python
def run_top_k(query: str, k: int = 5) -> list[dict]:
    """Run top-k similarity search, return list of result dicts."""
    results = vector_store.similarity_search_with_score(query, k=k)
    return [
        {
            "strategy": "top_k",
            "query": query,
            "chunk_text": doc.page_content,
            "metadata": doc.metadata,
            "score": float(score),
            "rank": i + 1,
        }
        for i, (doc, score) in enumerate(results)
    ]

# Test on one query first
sample = run_top_k(TEST_QUERIES[0], k=3)
print(f"Strategy 1 sample for: '{TEST_QUERIES[0]}'")
for r in sample:
    print(f"  Rank {r['rank']} | Score {r['score']:.4f} | {r['chunk_text'][:80]}...")
```

Expected: 3 ranked results with similarity scores.

---

## Task 6: Strategy 2 — MMR

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 9 — Strategy 2: MMR (code cell)**

```python
def run_mmr(query: str, k: int = 5, fetch_k: int = 20) -> list[dict]:
    """Run MMR search — retrieves fetch_k candidates, selects k diverse results."""
    results = vector_store.max_marginal_relevance_search(query, k=k, fetch_k=fetch_k)
    return [
        {
            "strategy": "mmr",
            "query": query,
            "chunk_text": doc.page_content,
            "metadata": doc.metadata,
            "score": None,   # MMR doesn't return raw similarity scores
            "rank": i + 1,
        }
        for i, doc in enumerate(results)
    ]

# Test on one query
sample_mmr = run_mmr(TEST_QUERIES[0], k=3)
print(f"Strategy 2 (MMR) sample for: '{TEST_QUERIES[0]}'")
for r in sample_mmr:
    print(f"  Rank {r['rank']} | {r['chunk_text'][:80]}...")
```

Expected: 3 results, likely more topically diverse than Top-K results.

---

## Task 7: Strategy 3 — Score threshold

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 10 — Strategy 3: Score threshold (code cell)**

```python
def run_threshold(query: str, k: int = 5, score_threshold: float = 0.75) -> list[dict]:
    """
    Run similarity search with a minimum score threshold.
    Note: PGVector uses L2 distance (lower = more similar).
    Adjust score_threshold based on observed score distributions.
    """
    retriever = vector_store.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={"k": k, "score_threshold": score_threshold},
    )
    results = retriever.invoke(query)
    return [
        {
            "strategy": f"threshold_{score_threshold}",
            "query": query,
            "chunk_text": doc.page_content,
            "metadata": doc.metadata,
            "score": None,
            "rank": i + 1,
        }
        for i, doc in enumerate(results)
    ]

# Test with a loose threshold first to understand score distribution
sample_threshold = run_threshold(TEST_QUERIES[0], k=5, score_threshold=0.5)
print(f"Strategy 3 (threshold=0.5) for: '{TEST_QUERIES[0]}'")
print(f"  Retrieved {len(sample_threshold)} results (vs 5 requested)")
for r in sample_threshold:
    print(f"  Rank {r['rank']} | {r['chunk_text'][:80]}...")
```

**Step 2: Add Cell 11 — Explore score distribution (code cell)**

This cell helps you calibrate the threshold before running the full eval.

```python
# Run top-k on all queries and collect score distributions
import numpy as np

all_scores = []
for q in TEST_QUERIES:
    results = vector_store.similarity_search_with_score(q, k=10)
    all_scores.extend([score for _, score in results])

scores_array = np.array(all_scores)
print("Score distribution across all queries (top-10 each):")
print(f"  Min:    {scores_array.min():.4f}")
print(f"  Max:    {scores_array.max():.4f}")
print(f"  Mean:   {scores_array.mean():.4f}")
print(f"  Median: {np.median(scores_array):.4f}")
print(f"  P25:    {np.percentile(scores_array, 25):.4f}")
print(f"  P75:    {np.percentile(scores_array, 75):.4f}")
print("\nUse these to calibrate score_threshold in run_threshold()")
```

Expected: Score statistics printed. Use the P25 value as your threshold to retrieve reasonably relevant chunks.

---

## Task 8: Strategy 4 — Hybrid BM25 + Semantic

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 12 — Strategy 4: Hybrid EnsembleRetriever (code cell)**

```python
# Build semantic retriever from PGVector
semantic_retriever = vector_store.as_retriever(search_kwargs={"k": 5})

# Combine BM25 + semantic with Reciprocal Rank Fusion
# weights: [bm25_weight, semantic_weight] — must sum to 1.0
# Giving semantic slightly more weight since Voyage AI embeddings are high quality
ensemble_retriever = EnsembleRetriever(
    retrievers=[bm25_retriever, semantic_retriever],
    weights=[0.4, 0.6],
)

def run_hybrid(query: str) -> list[dict]:
    """Run hybrid BM25 + semantic search via EnsembleRetriever."""
    results = ensemble_retriever.invoke(query)
    return [
        {
            "strategy": "hybrid_bm25_semantic",
            "query": query,
            "chunk_text": doc.page_content,
            "metadata": doc.metadata,
            "score": None,   # RRF score is internal
            "rank": i + 1,
        }
        for i, doc in enumerate(results)
    ]

# Test on one query
sample_hybrid = run_hybrid(TEST_QUERIES[0])
print(f"Strategy 4 (Hybrid) for: '{TEST_QUERIES[0]}'")
print(f"  Retrieved {len(sample_hybrid)} results")
for r in sample_hybrid:
    print(f"  Rank {r['rank']} | {r['chunk_text'][:80]}...")
```

Expected: Results that blend keyword and semantic matching — especially effective for Pali terms.

---

## Task 9: Run full evaluation across all queries

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 13 — Full eval run (code cell)**

```python
# Use the threshold calibrated from Task 7's score distribution
# Update SCORE_THRESHOLD based on what you saw in Cell 11
SCORE_THRESHOLD = 0.5   # Adjust after running Cell 11

all_results = []

for query in TEST_QUERIES:
    print(f"Running: {query[:50]}...")
    all_results.extend(run_top_k(query, k=5))
    all_results.extend(run_mmr(query, k=5, fetch_k=20))
    all_results.extend(run_threshold(query, k=5, score_threshold=SCORE_THRESHOLD))
    all_results.extend(run_hybrid(query))

df = pd.DataFrame(all_results)
print(f"\nTotal results collected: {len(df)}")
print(df.groupby("strategy")["query"].count().rename("result_count"))
```

Expected: A count of results per strategy. Threshold may return fewer than 5 per query.

**Step 2: Add Cell 14 — Manual inspection display (code cell)**

```python
def display_results_for_query(query: str, df: pd.DataFrame):
    """Display results for a single query across all strategies side by side."""
    subset = df[df["query"] == query]
    print(f"\n{'='*80}")
    print(f"QUERY: {query}")
    print(f"{'='*80}")
    for strategy in df["strategy"].unique():
        strat_results = subset[subset["strategy"] == strategy]
        print(f"\n--- {strategy.upper()} ({len(strat_results)} results) ---")
        for _, row in strat_results.iterrows():
            score_str = f"Score: {row['score']:.4f}" if row['score'] is not None else "Score: N/A"
            print(f"  [{score_str}] {row['chunk_text'][:150]}...")
        print()

# Inspect 2-3 queries manually before running Groq judge
display_results_for_query(TEST_QUERIES[0], df)
display_results_for_query(TEST_QUERIES[6], df)  # Pali-specific: "What does anicca mean?"
```

---

## Task 10: Groq LLM-as-judge scoring

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 15 — Groq judge function (code cell)**

```python
groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

JUDGE_PROMPT = """Given this query: "{query}"

And this retrieved chunk:
\"\"\"
{chunk_text}
\"\"\"

Rate the relevance of this chunk to the query on a scale of 1-5:
1 = Not relevant at all
2 = Tangentially related
3 = Partially relevant
4 = Mostly relevant
5 = Highly relevant, directly answers the query

Reply with ONLY valid JSON, no other text: {{"score": <int>, "reason": "<one sentence>"}}"""


def judge_relevance(query: str, chunk_text: str) -> dict:
    """Ask Groq to score relevance of a chunk for a query. Returns {"score": int, "reason": str}."""
    prompt = JUDGE_PROMPT.format(query=query, chunk_text=chunk_text[:800])  # cap at 800 chars
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
        print(f"  Judge error: {e} | raw: {raw if 'raw' in dir() else 'N/A'}")
        return {"score": -1, "reason": "error"}


# Test judge on one pair
sample_score = judge_relevance(TEST_QUERIES[0], all_results[0]["chunk_text"])
print(f"Sample judge output: {sample_score}")
```

Expected: `Sample judge output: {'score': 4, 'reason': '...'}`

**Step 2: Add Cell 16 — Run judge on all results (code cell)**

```python
# NOTE: This makes one Groq API call per result row.
# With 10 queries × ~4 strategies × 5 results = ~200 calls.
# Groq free tier allows 30 req/min on llama-3.3-70b — add sleep if rate-limited.
import time

scores = []
errors = 0
total = len(df)

for i, row in df.iterrows():
    result = judge_relevance(row["query"], row["chunk_text"])
    scores.append(result.get("score", -1))
    if result.get("score", -1) == -1:
        errors += 1
    if (i + 1) % 30 == 0:
        print(f"  Processed {i+1}/{total} | Errors so far: {errors}")
        time.sleep(2)  # brief pause to stay within rate limit

df["groq_score"] = scores
df["groq_scored"] = df["groq_score"] > 0

print(f"\nScoring complete. Errors: {errors}/{total}")
print(df.groupby("strategy")["groq_score"].mean().round(2))
```

Expected: Mean Groq scores per strategy printed.

---

## Task 11: Summary table and analysis

**Files:**
- Modify: `experiments/rag_retrieval_eval.ipynb` (add cells)

**Step 1: Add Cell 17 — Summary comparison table (code cell)**

```python
# Build summary table: one row per strategy
valid_df = df[df["groq_scored"]]  # exclude errored rows

summary = valid_df.groupby("strategy").agg(
    avg_groq_score=("groq_score", "mean"),
    avg_similarity_score=("score", lambda x: x.dropna().mean() if x.dropna().any() else None),
    avg_results_per_query=("rank", lambda x: len(x) / len(TEST_QUERIES)),
    total_results=("chunk_text", "count"),
).round(3)

print("\n" + "="*60)
print("RETRIEVAL STRATEGY COMPARISON")
print("="*60)
print(summary.to_string())
print("\nHigher groq_score = more relevant results")
print("avg_similarity_score: only available for top_k and threshold strategies")
```

**Step 2: Add Cell 18 — Score distribution plot (code cell)**

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Plot 1: Groq score distribution per strategy
strategies = df["strategy"].unique()
score_data = [valid_df[valid_df["strategy"] == s]["groq_score"].values for s in strategies]
axes[0].boxplot(score_data, labels=strategies, vert=True)
axes[0].set_title("Groq Relevance Score Distribution by Strategy")
axes[0].set_ylabel("Relevance Score (1-5)")
axes[0].tick_params(axis='x', rotation=30)

# Plot 2: Average score per strategy (bar)
summary["avg_groq_score"].plot(kind="bar", ax=axes[1], color="steelblue")
axes[1].set_title("Average Groq Score by Strategy")
axes[1].set_ylabel("Avg Relevance Score")
axes[1].tick_params(axis='x', rotation=30)

plt.tight_layout()
plt.savefig("retrieval_eval_results.png", dpi=150, bbox_inches="tight")
plt.show()
print("Plot saved to retrieval_eval_results.png")
```

**Step 3: Add Cell 19 — Per-query breakdown (code cell)**

```python
# Show which strategy wins per query
query_summary = valid_df.groupby(["query", "strategy"])["groq_score"].mean().unstack()
print("\nAverage Groq Score per Query × Strategy:")
print(query_summary.round(2).to_string())

# Highlight winner per query
best_per_query = query_summary.idxmax(axis=1)
print("\nBest strategy per query:")
for q, best in best_per_query.items():
    print(f"  {q[:50]:<52} → {best}")
```

**Step 4: Run all cells end-to-end**

Run the entire notebook via `Kernel → Restart & Run All`. Verify:
- No import errors
- Chunk loading shows > 0 chunks
- All 4 strategies return results
- Groq scoring has < 5% error rate
- Summary table renders

**Step 5: Save the notebook output**

```bash
poetry run jupyter nbconvert --to notebook --execute experiments/rag_retrieval_eval.ipynb \
  --output experiments/rag_retrieval_eval.ipynb
```

**Step 6: Commit**

```bash
git add experiments/rag_retrieval_eval.ipynb experiments/retrieval_eval_results.png
git commit -m "feat: add RAG retrieval quality evaluation notebook (4 strategies + Groq judge)"
```

---

## Notes

### Score interpretation for PGVector
PGVector with Voyage AI uses **cosine similarity** (higher = more similar, range 0–1). A `score_threshold` of 0.5–0.7 is typically a reasonable starting point; calibrate using Cell 11's score distribution output.

### Groq rate limits
Free tier: 30 requests/minute for `llama-3.3-70b-versatile`. With ~200 calls the `time.sleep(2)` every 30 calls should stay within limits. If you hit `429` errors, increase the sleep to `5`.

### BM25 note
`BM25Retriever` operates in-memory on loaded documents. For large corpora (>50k chunks), the initial `from_documents()` call may take 10–30 seconds but is a one-time cost per notebook session.

### Ensemble weights
`[0.4, 0.6]` (BM25, semantic) is a reasonable starting point. You can experiment with `[0.5, 0.5]` or `[0.3, 0.7]` — add an extra cell to compare different weight configurations if you want.
