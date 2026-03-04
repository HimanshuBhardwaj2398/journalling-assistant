# Retrieval Evaluation Dataset — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a ~100-pair ground-truth eval dataset from Pali Canon chunks using Groq, then evaluate retrieval strategies with standard IR metrics.

**Architecture:** A two-notebook approach: (1) `experiments/eval_dataset_generation.ipynb` generates and filters QA pairs into a JSONL file, (2) `experiments/retrieval_eval_metrics.ipynb` uses that file to compute Recall@K, Precision@K, MRR, NDCG across all 4 retrieval strategies.

**Tech Stack:** Groq SDK (llama-3.3-70b-versatile), SQLAlchemy, LangChain PGVector, Voyage AI embeddings, pandas, matplotlib

---

### Task 1: Create data directory and eval dataset generation notebook skeleton

**Files:**
- Create: `data/.gitkeep`
- Create: `experiments/eval_dataset_generation.ipynb`

**Step 1: Create directory**

```bash
mkdir -p data
touch data/.gitkeep
```

**Step 2: Create notebook with setup cells**

Create `experiments/eval_dataset_generation.ipynb` with these initial cells:

**Cell 0 (markdown):**
```markdown
# Retrieval Evaluation Dataset Generator

Generates ~100 ground-truth QA pairs from Pali Canon chunks using Groq (llama-3.3-70b-versatile).

**Pipeline:**
1. Sample ~200 chunks from database (stratified by document)
2. Generate question + answer per chunk via Groq
3. Filter with 3 critique agents (groundedness, standalone, relevance)
4. Deduplicate via embedding similarity
5. Export to `data/eval_dataset.jsonl`
```

**Cell 1 (code) — Imports and env validation:**
```python
import asyncio
import json
import os
import random
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from groq import Groq
from sqlalchemy import func

load_dotenv()

# Validate required env vars
required_vars = ["GROQ_API_KEY", "DB_URL"]
missing = [v for v in required_vars if not os.getenv(v)]
if missing:
    raise EnvironmentError(f"Missing env vars: {missing}")

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
print("✓ Groq client initialized")
print(f"✓ DB_URL set: {os.getenv('DB_URL')[:30]}...")
```

**Step 3: Commit**

```bash
git add data/.gitkeep experiments/eval_dataset_generation.ipynb
git commit -m "feat: scaffold eval dataset generation notebook"
```

---

### Task 2: Load and sample chunks from database

**Files:**
- Modify: `experiments/eval_dataset_generation.ipynb` (add cells 2-3)

**Step 1: Add Cell 2 (code) — Load all chunks with document info:**

```python
import sys
sys.path.insert(0, "..")

from db.database import session_scope
from db.schema import Chunk, Document

with session_scope() as session:
    # Load all chunks with parent document title
    results = (
        session.query(
            Chunk.id,
            Chunk.uuid,
            Chunk.chunk_text,
            Chunk.chunk_index,
            Chunk.chunk_metadata,
            Chunk.document_id,
            Document.title,
        )
        .join(Document, Chunk.document_id == Document.id)
        .all()
    )

all_chunks = [
    {
        "id": r.id,
        "uuid": r.uuid,
        "chunk_text": r.chunk_text,
        "chunk_index": r.chunk_index,
        "chunk_metadata": r.chunk_metadata,
        "document_id": r.document_id,
        "document_title": r.title,
    }
    for r in results
]

print(f"✓ Loaded {len(all_chunks)} chunks from {len(set(c['document_id'] for c in all_chunks))} documents")

# Show distribution
doc_counts = {}
for c in all_chunks:
    doc_counts[c["document_title"]] = doc_counts.get(c["document_title"], 0) + 1
for title, count in sorted(doc_counts.items()):
    print(f"  {title}: {count} chunks")
```

**Step 2: Add Cell 3 (code) — Stratified sampling:**

```python
SAMPLE_SIZE = 200
random.seed(42)

# Group chunks by document
from collections import defaultdict
chunks_by_doc = defaultdict(list)
for chunk in all_chunks:
    chunks_by_doc[chunk["document_id"]].append(chunk)

# Proportional sampling per document
total_chunks = len(all_chunks)
sampled_chunks = []
for doc_id, doc_chunks in chunks_by_doc.items():
    proportion = len(doc_chunks) / total_chunks
    n_samples = max(1, round(SAMPLE_SIZE * proportion))
    sampled = random.sample(doc_chunks, min(n_samples, len(doc_chunks)))
    sampled_chunks.extend(sampled)

# Trim to exact target if oversampled
if len(sampled_chunks) > SAMPLE_SIZE:
    sampled_chunks = random.sample(sampled_chunks, SAMPLE_SIZE)

print(f"✓ Sampled {len(sampled_chunks)} chunks (target: {SAMPLE_SIZE})")

# Verify distribution
sampled_doc_counts = {}
for c in sampled_chunks:
    sampled_doc_counts[c["document_title"]] = sampled_doc_counts.get(c["document_title"], 0) + 1
for title, count in sorted(sampled_doc_counts.items()):
    print(f"  {title}: {count} sampled chunks")
```

**Step 3: Commit**

```bash
git add experiments/eval_dataset_generation.ipynb
git commit -m "feat: add chunk loading and stratified sampling"
```

---

### Task 3: Implement QA generation with Groq

**Files:**
- Modify: `experiments/eval_dataset_generation.ipynb` (add cells 4-5)

**Step 1: Add Cell 4 (code) — QA generation prompt and function:**

```python
QA_GENERATION_PROMPT = """Your task is to write a question and answer given a passage from Buddhist scripture (Pali Canon).

Requirements:
- The question should be answerable from the passage
- Phrase it as a real meditation practitioner or student might ask
- Do NOT reference "the passage", "the text", or "according to" — write as if asking a teacher
- The answer should be concise (1-3 sentences) and grounded strictly in the passage
- Classify the question type as one of: factual, conceptual, practical, cross_textual, pali_specific

Definitions:
- factual: Answerable with a specific fact from the passage ("What are the four...?")
- conceptual: Requires understanding relationships or meaning ("How does X relate to Y?")
- practical: About meditation practice or technique ("How does one develop...?")
- cross_textual: Could relate to themes across multiple texts ("What role does X play in...?")
- pali_specific: Uses or asks about Pali terminology ("What does X mean?")

Context: {chunk_text}

Reply with ONLY valid JSON (no markdown, no code fences):
{{"question": "...", "answer": "...", "question_type": "..."}}"""


def generate_qa(chunk: dict, max_retries: int = 2) -> dict | None:
    """Generate a QA pair from a chunk using Groq."""
    for attempt in range(max_retries + 1):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "user", "content": QA_GENERATION_PROMPT.format(chunk_text=chunk["chunk_text"])}
                ],
                temperature=0.7,
                max_tokens=500,
            )
            content = response.choices[0].message.content.strip()
            # Handle potential markdown code fences
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)

            # Validate required fields
            if not all(k in parsed for k in ("question", "answer", "question_type")):
                raise ValueError("Missing required fields")

            return {
                "question": parsed["question"],
                "answer": parsed["answer"],
                "question_type": parsed["question_type"],
                "chunk_uuid": chunk["uuid"],
                "chunk_text": chunk["chunk_text"],
                "document_id": chunk["document_id"],
                "document_title": chunk["document_title"],
            }
        except (json.JSONDecodeError, ValueError, KeyError) as e:
            if attempt < max_retries:
                time.sleep(1)
                continue
            print(f"  ✗ Failed for chunk {chunk['uuid'][:8]}: {e}")
            return None
        except Exception as e:
            print(f"  ✗ API error for chunk {chunk['uuid'][:8]}: {e}")
            time.sleep(2)
            if attempt < max_retries:
                continue
            return None

print("✓ QA generation function defined")
```

**Step 2: Add Cell 5 (code) — Run generation with rate limiting:**

```python
# Groq free tier: 30 requests/min
RATE_LIMIT_DELAY = 2.1  # seconds between requests (safe margin)

raw_qa_pairs = []
failed_count = 0

print(f"Generating QA pairs for {len(sampled_chunks)} chunks...")
print(f"Estimated time: ~{len(sampled_chunks) * RATE_LIMIT_DELAY / 60:.1f} minutes")

for i, chunk in enumerate(sampled_chunks):
    if i > 0 and i % 10 == 0:
        print(f"  Progress: {i}/{len(sampled_chunks)} ({len(raw_qa_pairs)} generated, {failed_count} failed)")

    result = generate_qa(chunk)
    if result:
        raw_qa_pairs.append(result)
    else:
        failed_count += 1

    time.sleep(RATE_LIMIT_DELAY)

print(f"\n✓ Generated {len(raw_qa_pairs)} QA pairs ({failed_count} failures)")
print(f"Success rate: {len(raw_qa_pairs) / len(sampled_chunks) * 100:.1f}%")

# Preview question type distribution
type_counts = {}
for qa in raw_qa_pairs:
    t = qa["question_type"]
    type_counts[t] = type_counts.get(t, 0) + 1
print(f"\nQuestion type distribution:")
for t, count in sorted(type_counts.items()):
    print(f"  {t}: {count}")
```

**Step 3: Commit**

```bash
git add experiments/eval_dataset_generation.ipynb
git commit -m "feat: add Groq QA generation with rate limiting"
```

---

### Task 4: Implement three-agent quality filtering

**Files:**
- Modify: `experiments/eval_dataset_generation.ipynb` (add cells 6-7)

**Step 1: Add Cell 6 (code) — Critique agent prompts and scorer:**

```python
GROUNDEDNESS_PROMPT = """You are evaluating a question-answer pair generated from a passage.

Rate the GROUNDEDNESS of the question on a scale of 1-5:
1 = Question cannot be answered from this passage at all
2 = Question is only loosely related to the passage
3 = Question is partially answerable from the passage
4 = Question is mostly answerable from the passage
5 = Question is fully and directly answerable from the passage

Passage: {chunk_text}
Question: {question}
Answer: {answer}

Reply with ONLY valid JSON: {{"score": <int>, "reason": "<one sentence>"}}"""

STANDALONE_PROMPT = """You are evaluating whether a question makes sense on its own, without needing to see the source passage.

Rate the STANDALONE quality on a scale of 1-5:
1 = Impossible to understand without context (e.g., "What does the above describe?")
2 = Very unclear without context
3 = Somewhat understandable but vague
4 = Mostly clear and self-contained
5 = Perfectly clear question that anyone could understand

Question: {question}

Reply with ONLY valid JSON: {{"score": <int>, "reason": "<one sentence>"}}"""

RELEVANCE_PROMPT = """You are evaluating whether a question about Buddhist meditation and philosophy is realistic.

Rate the RELEVANCE on a scale of 1-5:
1 = No real practitioner would ask this (too artificial or academic)
2 = Very unlikely question
3 = Possible but unusual
4 = A practitioner might reasonably ask this
5 = Very natural question a meditator or student would ask

Question: {question}

Reply with ONLY valid JSON: {{"score": <int>, "reason": "<one sentence>"}}"""


def score_qa(qa: dict, prompt_template: str, prompt_kwargs: dict, max_retries: int = 2) -> int | None:
    """Score a QA pair using a Groq critique agent. Returns score 1-5 or None on failure."""
    for attempt in range(max_retries + 1):
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "user", "content": prompt_template.format(**prompt_kwargs)}
                ],
                temperature=0.0,
                max_tokens=100,
            )
            content = response.choices[0].message.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(content)
            score = int(parsed["score"])
            if 1 <= score <= 5:
                return score
            return None
        except Exception:
            if attempt < max_retries:
                time.sleep(2)
                continue
            return None

print("✓ Critique agent functions defined")
```

**Step 2: Add Cell 7 (code) — Run filtering on all raw QA pairs:**

```python
FILTER_THRESHOLD = 4

print(f"Filtering {len(raw_qa_pairs)} QA pairs with 3 critique agents...")
print(f"Total API calls: ~{len(raw_qa_pairs) * 3}")
print(f"Estimated time: ~{len(raw_qa_pairs) * 3 * RATE_LIMIT_DELAY / 60:.1f} minutes")

scored_qa_pairs = []

for i, qa in enumerate(raw_qa_pairs):
    if i > 0 and i % 20 == 0:
        passed = sum(1 for s in scored_qa_pairs if s.get("passed", False))
        print(f"  Progress: {i}/{len(raw_qa_pairs)} ({passed} passed so far)")

    # Score groundedness
    g_score = score_qa(qa, GROUNDEDNESS_PROMPT, {
        "chunk_text": qa["chunk_text"],
        "question": qa["question"],
        "answer": qa["answer"],
    })
    time.sleep(RATE_LIMIT_DELAY)

    # Score standalone quality
    s_score = score_qa(qa, STANDALONE_PROMPT, {
        "question": qa["question"],
    })
    time.sleep(RATE_LIMIT_DELAY)

    # Score relevance
    r_score = score_qa(qa, RELEVANCE_PROMPT, {
        "question": qa["question"],
    })
    time.sleep(RATE_LIMIT_DELAY)

    qa_scored = {
        **qa,
        "groundedness_score": g_score,
        "standalone_score": s_score,
        "relevance_score": r_score,
        "passed": all(
            s is not None and s >= FILTER_THRESHOLD
            for s in [g_score, s_score, r_score]
        ),
    }
    scored_qa_pairs.append(qa_scored)

passed = [qa for qa in scored_qa_pairs if qa["passed"]]
failed = [qa for qa in scored_qa_pairs if not qa["passed"]]

print(f"\n✓ Filtering complete")
print(f"  Passed: {len(passed)} ({len(passed)/len(scored_qa_pairs)*100:.1f}%)")
print(f"  Failed: {len(failed)} ({len(failed)/len(scored_qa_pairs)*100:.1f}%)")

# Show score distributions
for metric in ["groundedness_score", "standalone_score", "relevance_score"]:
    scores = [qa[metric] for qa in scored_qa_pairs if qa[metric] is not None]
    print(f"  {metric}: avg={sum(scores)/len(scores):.2f}, min={min(scores)}, max={max(scores)}")
```

**Step 3: Commit**

```bash
git add experiments/eval_dataset_generation.ipynb
git commit -m "feat: add three-agent quality filtering pipeline"
```

---

### Task 5: Implement deduplication and export to JSONL

**Files:**
- Modify: `experiments/eval_dataset_generation.ipynb` (add cells 8-10)

**Step 1: Add Cell 8 (code) — Deduplicate using Voyage AI embeddings:**

```python
from langchain_voyageai import VoyageAIEmbeddings
import numpy as np

# Embed all passing questions
voyage = VoyageAIEmbeddings(model="voyage-3.5")
questions = [qa["question"] for qa in passed]
question_embeddings = voyage.embed_documents(questions)

print(f"✓ Embedded {len(question_embeddings)} questions")

# Find near-duplicates (cosine similarity > 0.9)
embeddings_array = np.array(question_embeddings)
# Normalize for cosine similarity
norms = np.linalg.norm(embeddings_array, axis=1, keepdims=True)
normalized = embeddings_array / norms

similarity_matrix = normalized @ normalized.T

# Find pairs to remove (keep the first, remove the second)
to_remove = set()
for i in range(len(passed)):
    if i in to_remove:
        continue
    for j in range(i + 1, len(passed)):
        if j in to_remove:
            continue
        if similarity_matrix[i][j] > 0.9:
            to_remove.add(j)

deduplicated = [qa for i, qa in enumerate(passed) if i not in to_remove]

print(f"✓ Removed {len(to_remove)} near-duplicate questions")
print(f"✓ Final dataset: {len(deduplicated)} QA pairs")
```

**Step 2: Add Cell 9 (code) — Export to JSONL:**

```python
OUTPUT_PATH = Path("../data/eval_dataset.jsonl")
OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

records = []
for i, qa in enumerate(deduplicated):
    record = {
        "id": f"eval_{i+1:03d}",
        "question": qa["question"],
        "reference_answer": qa["answer"],
        "reference_contexts": [qa["chunk_text"]],
        "chunk_ids": [qa["chunk_uuid"]],
        "source_document_id": qa["document_id"],
        "metadata": {
            "question_type": qa["question_type"],
            "groundedness_score": qa["groundedness_score"],
            "standalone_score": qa["standalone_score"],
            "relevance_score": qa["relevance_score"],
            "source_document_title": qa["document_title"],
        },
    }
    records.append(record)

with open(OUTPUT_PATH, "w") as f:
    for record in records:
        f.write(json.dumps(record) + "\n")

print(f"✓ Saved {len(records)} records to {OUTPUT_PATH}")
```

**Step 3: Add Cell 10 (code) — Summary statistics:**

```python
df = pd.DataFrame([
    {
        "id": r["id"],
        "question_type": r["metadata"]["question_type"],
        "groundedness": r["metadata"]["groundedness_score"],
        "standalone": r["metadata"]["standalone_score"],
        "relevance": r["metadata"]["relevance_score"],
        "source_doc": r["metadata"]["source_document_title"],
        "question_length": len(r["question"]),
        "answer_length": len(r["reference_answer"]),
    }
    for r in records
])

print("=== Eval Dataset Summary ===")
print(f"Total QA pairs: {len(df)}")
print(f"\nBy question type:")
print(df["question_type"].value_counts().to_string())
print(f"\nBy source document:")
print(df["source_doc"].value_counts().to_string())
print(f"\nScore distributions:")
for col in ["groundedness", "standalone", "relevance"]:
    print(f"  {col}: mean={df[col].mean():.2f}, std={df[col].std():.2f}")
print(f"\nQuestion length: mean={df['question_length'].mean():.0f}, std={df['question_length'].std():.0f}")
print(f"Answer length: mean={df['answer_length'].mean():.0f}, std={df['answer_length'].std():.0f}")
```

**Step 4: Commit**

```bash
git add experiments/eval_dataset_generation.ipynb data/.gitkeep
git commit -m "feat: add deduplication and JSONL export"
```

---

### Task 6: Create retrieval evaluation metrics notebook — setup and data loading

**Files:**
- Create: `experiments/retrieval_eval_metrics.ipynb`

**Step 1: Create notebook with initial cells**

**Cell 0 (markdown):**
```markdown
# Retrieval Strategy Evaluation with Ground-Truth Metrics

Uses `data/eval_dataset.jsonl` to compute standard IR metrics across 4 retrieval strategies:
- **Recall@K**: Was the ground-truth chunk in the top K?
- **Precision@K**: What fraction of retrieved chunks are relevant?
- **MRR**: Average reciprocal rank of first relevant result
- **NDCG@K**: Rank-weighted relevance quality
- **Hit Rate@K**: At least one relevant chunk in top K?
```

**Cell 1 (code) — Imports and setup:**
```python
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, "..")
load_dotenv()

# Load eval dataset
EVAL_PATH = Path("../data/eval_dataset.jsonl")
eval_data = []
with open(EVAL_PATH) as f:
    for line in f:
        eval_data.append(json.loads(line))

print(f"✓ Loaded {len(eval_data)} evaluation QA pairs")

# Preview
for qa in eval_data[:3]:
    print(f"\n  [{qa['metadata']['question_type']}] {qa['question']}")
    print(f"  Answer: {qa['reference_answer'][:80]}...")
```

**Cell 2 (code) — Connect to vector store and load chunks for BM25:**
```python
from db.database import session_scope
from db.schema import Chunk, Document
from ingestion.embed import VectorStoreConfig, VectorStoreManager
from rank_bm25 import BM25Okapi
from langchain_core.documents import Document as LCDocument
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever

# Connect to PGVector
config = VectorStoreConfig()
vsm = VectorStoreManager(config)
vector_store = vsm.vector_store
print(f"✓ Connected to PGVector collection: {config.collection_name}")

# Load all chunks for BM25
with session_scope() as session:
    db_chunks = session.query(Chunk).all()
    chunk_docs = [
        LCDocument(
            page_content=c.chunk_text,
            metadata={"uuid": c.uuid, "document_id": c.document_id, **(c.chunk_metadata or {})},
        )
        for c in db_chunks
    ]

bm25_retriever = BM25Retriever.from_documents(chunk_docs, k=5)
print(f"✓ Built BM25 index over {len(chunk_docs)} chunks")
```

**Step 2: Commit**

```bash
git add experiments/retrieval_eval_metrics.ipynb
git commit -m "feat: scaffold retrieval eval metrics notebook"
```

---

### Task 7: Implement retrieval strategies and metric computation

**Files:**
- Modify: `experiments/retrieval_eval_metrics.ipynb` (add cells 3-6)

**Step 1: Add Cell 3 (code) — Define retrieval strategies:**

```python
def retrieve_topk(query: str, k: int = 5) -> list[dict]:
    """Strategy 1: Top-K similarity search."""
    results = vector_store.similarity_search_with_score(query, k=k)
    return [
        {"uuid": doc.metadata.get("uuid", ""), "score": float(score), "text": doc.page_content}
        for doc, score in results
    ]

def retrieve_mmr(query: str, k: int = 5) -> list[dict]:
    """Strategy 2: MMR (Maximal Marginal Relevance)."""
    results = vector_store.max_marginal_relevance_search(query, k=k, fetch_k=20)
    return [
        {"uuid": doc.metadata.get("uuid", ""), "score": None, "text": doc.page_content}
        for doc in results
    ]

def retrieve_threshold(query: str, k: int = 5, threshold: float = 0.7) -> list[dict]:
    """Strategy 3: Similarity score threshold."""
    results = vector_store.similarity_search_with_score(query, k=k)
    return [
        {"uuid": doc.metadata.get("uuid", ""), "score": float(score), "text": doc.page_content}
        for doc, score in results
        if float(score) >= threshold
    ]

def retrieve_hybrid(query: str, k: int = 5) -> list[dict]:
    """Strategy 4: Hybrid BM25 + Semantic (EnsembleRetriever)."""
    semantic_retriever = vector_store.as_retriever(search_kwargs={"k": k})
    ensemble = EnsembleRetriever(
        retrievers=[bm25_retriever, semantic_retriever],
        weights=[0.4, 0.6],
    )
    results = ensemble.invoke(query)[:k]
    return [
        {"uuid": doc.metadata.get("uuid", ""), "score": None, "text": doc.page_content}
        for doc in results
    ]

strategies = {
    "Top-K": retrieve_topk,
    "MMR": retrieve_mmr,
    "Threshold": retrieve_threshold,
    "Hybrid (BM25+Semantic)": retrieve_hybrid,
}

print(f"✓ Defined {len(strategies)} retrieval strategies")
```

**Step 2: Add Cell 4 (code) — Run all strategies on all eval questions:**

```python
import time

all_results = {}  # {strategy_name: [{query_id, retrieved_uuids, ground_truth_uuids}, ...]}

for strategy_name, retrieve_fn in strategies.items():
    print(f"\nRunning: {strategy_name}")
    strategy_results = []

    for qa in eval_data:
        retrieved = retrieve_fn(qa["question"])
        strategy_results.append({
            "eval_id": qa["id"],
            "question": qa["question"],
            "question_type": qa["metadata"]["question_type"],
            "ground_truth_uuids": set(qa["chunk_ids"]),
            "retrieved_uuids": [r["uuid"] for r in retrieved],
            "n_retrieved": len(retrieved),
        })

    all_results[strategy_name] = strategy_results
    print(f"  ✓ {len(strategy_results)} queries processed")

print(f"\n✓ All strategies complete")
```

**Step 3: Add Cell 5 (code) — Compute IR metrics:**

```python
def compute_metrics(results: list[dict], k: int = 5) -> dict:
    """Compute IR metrics for a list of query results."""
    recalls = []
    precisions = []
    reciprocal_ranks = []
    ndcgs = []
    hits = []

    for r in results:
        gt = r["ground_truth_uuids"]
        retrieved = r["retrieved_uuids"][:k]

        # Recall@K: fraction of ground truth found in top K
        found = sum(1 for uuid in retrieved if uuid in gt)
        recall = found / len(gt) if gt else 0
        recalls.append(recall)

        # Precision@K: fraction of retrieved that are relevant
        precision = found / len(retrieved) if retrieved else 0
        precisions.append(precision)

        # Hit Rate@K: binary — at least one hit
        hit = 1 if found > 0 else 0
        hits.append(hit)

        # MRR: reciprocal rank of first relevant result
        rr = 0
        for rank, uuid in enumerate(retrieved, 1):
            if uuid in gt:
                rr = 1.0 / rank
                break
        reciprocal_ranks.append(rr)

        # NDCG@K
        dcg = 0
        for rank, uuid in enumerate(retrieved, 1):
            rel = 1 if uuid in gt else 0
            dcg += rel / np.log2(rank + 1)
        # Ideal DCG: all relevant docs at top
        ideal_rels = sorted([1] * min(len(gt), k) + [0] * max(0, k - len(gt)), reverse=True)
        idcg = sum(rel / np.log2(rank + 2) for rank, rel in enumerate(ideal_rels))
        ndcg = dcg / idcg if idcg > 0 else 0
        ndcgs.append(ndcg)

    return {
        f"Recall@{k}": np.mean(recalls),
        f"Precision@{k}": np.mean(precisions),
        "MRR": np.mean(reciprocal_ranks),
        f"NDCG@{k}": np.mean(ndcgs),
        f"Hit Rate@{k}": np.mean(hits),
    }

# Compute for all strategies
metrics_table = {}
for strategy_name, results in all_results.items():
    metrics_table[strategy_name] = compute_metrics(results, k=5)

metrics_df = pd.DataFrame(metrics_table).T
metrics_df = metrics_df.round(4)
print("=== Strategy Comparison ===")
print(metrics_df.to_string())
```

**Step 4: Add Cell 6 (code) — Per-question-type breakdown:**

```python
print("=== Per-Question-Type Breakdown ===\n")

for strategy_name, results in all_results.items():
    print(f"\n--- {strategy_name} ---")
    by_type = {}
    for r in results:
        qt = r["question_type"]
        if qt not in by_type:
            by_type[qt] = []
        by_type[qt].append(r)

    type_metrics = {}
    for qt, qt_results in sorted(by_type.items()):
        m = compute_metrics(qt_results, k=5)
        type_metrics[qt] = m

    type_df = pd.DataFrame(type_metrics).T
    print(type_df.round(4).to_string())
```

**Step 5: Commit**

```bash
git add experiments/retrieval_eval_metrics.ipynb
git commit -m "feat: add retrieval strategies and IR metric computation"
```

---

### Task 8: Add visualization

**Files:**
- Modify: `experiments/retrieval_eval_metrics.ipynb` (add cells 7-8)

**Step 1: Add Cell 7 (code) — Bar chart comparing strategies:**

```python
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 5, figsize=(20, 5))
fig.suptitle("Retrieval Strategy Comparison", fontsize=14, fontweight="bold")

for idx, metric in enumerate(metrics_df.columns):
    ax = axes[idx]
    bars = ax.bar(range(len(metrics_df)), metrics_df[metric], color=["#2196F3", "#4CAF50", "#FF9800", "#9C27B0"])
    ax.set_title(metric, fontsize=11)
    ax.set_xticks(range(len(metrics_df)))
    ax.set_xticklabels(metrics_df.index, rotation=45, ha="right", fontsize=8)
    ax.set_ylim(0, 1)
    ax.grid(axis="y", alpha=0.3)

    # Add value labels on bars
    for bar, val in zip(bars, metrics_df[metric]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.02,
                f"{val:.3f}", ha="center", va="bottom", fontsize=8)

plt.tight_layout()
plt.savefig("../data/retrieval_eval_comparison.png", dpi=150, bbox_inches="tight")
plt.show()
print("✓ Saved visualization to data/retrieval_eval_comparison.png")
```

**Step 2: Add Cell 8 (code) — Hit rate by question type heatmap:**

```python
# Build heatmap data: strategies × question types for Hit Rate@5
heatmap_data = {}
for strategy_name, results in all_results.items():
    by_type = {}
    for r in results:
        qt = r["question_type"]
        if qt not in by_type:
            by_type[qt] = []
        by_type[qt].append(r)

    row = {}
    for qt, qt_results in sorted(by_type.items()):
        m = compute_metrics(qt_results, k=5)
        row[qt] = m["Hit Rate@5"]
    heatmap_data[strategy_name] = row

heatmap_df = pd.DataFrame(heatmap_data).T
fig, ax = plt.subplots(figsize=(10, 4))
im = ax.imshow(heatmap_df.values, cmap="YlGn", aspect="auto", vmin=0, vmax=1)

ax.set_xticks(range(len(heatmap_df.columns)))
ax.set_xticklabels(heatmap_df.columns, rotation=45, ha="right")
ax.set_yticks(range(len(heatmap_df.index)))
ax.set_yticklabels(heatmap_df.index)

# Add text annotations
for i in range(len(heatmap_df.index)):
    for j in range(len(heatmap_df.columns)):
        val = heatmap_df.values[i, j]
        ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                color="white" if val > 0.7 else "black", fontsize=10)

ax.set_title("Hit Rate@5 by Strategy × Question Type")
plt.colorbar(im, ax=ax, label="Hit Rate")
plt.tight_layout()
plt.savefig("../data/retrieval_eval_heatmap.png", dpi=150, bbox_inches="tight")
plt.show()
print("✓ Saved heatmap to data/retrieval_eval_heatmap.png")
```

**Step 3: Commit**

```bash
git add experiments/retrieval_eval_metrics.ipynb
git commit -m "feat: add strategy comparison visualizations"
```

---

### Task 9: Add .gitignore entries and final commit

**Files:**
- Modify: `.gitignore`

**Step 1: Add data artifacts to .gitignore**

Add these lines to `.gitignore`:
```
# Eval dataset outputs (generated, not tracked)
data/eval_dataset.jsonl
data/*.png
```

Note: `data/.gitkeep` ensures the directory exists. The generated JSONL and PNGs are output artifacts that should be regenerated, not version-controlled.

**Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add eval data artifacts to gitignore"
```

---

## Execution Notes

**Prerequisites before running:**
1. Database must have ingested Pali Canon chunks (status = COMPLETED)
2. `.env` must have `GROQ_API_KEY`, `DB_URL`, and `VOYAGE_API_KEY` set
3. Generation notebook takes ~20-25 minutes total (rate-limited Groq calls)
4. Metrics notebook runs in ~2-3 minutes (retrieval is fast)

**If Groq rate limits are hit:**
- The generation notebook uses 2.1s delay between calls (safe for 30 req/min)
- If daily token limit (100K) is hit mid-run, save `raw_qa_pairs` / `scored_qa_pairs` to a JSON file and resume next day
- Total budget: ~800 API calls, ~90K tokens — fits in one day

**If fewer than 100 pairs pass filtering:**
- Lower `FILTER_THRESHOLD` from 4 to 3 (less strict)
- Or increase `SAMPLE_SIZE` from 200 to 250 and re-run generation
