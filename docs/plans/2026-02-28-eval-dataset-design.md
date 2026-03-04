# Retrieval Evaluation Dataset — Design Doc

**Date**: 2026-02-28
**Status**: Approved
**Artifacts**: `experiments/eval_dataset_generation.ipynb`, `data/eval_dataset.jsonl`

## Goal

Build a ground-truth evaluation dataset of ~100 question-context pairs, synthetically generated from existing Pali Canon chunks using Groq, to:

1. Measure absolute retrieval quality with standard IR metrics (Recall@K, Precision@K, MRR, NDCG)
2. Compare the 4 retrieval strategies (Top-K, MMR, Threshold, Hybrid BM25+Semantic) with proper ground truth

## Approach

**Custom pipeline with Groq** (llama-3.3-70b-versatile, free tier). Chosen over RAGAS TestsetGenerator (documented bugs: infinite loops, incorrect ground truth, breaking changes) and DeepEval Synthesizer (overkill for a ~100-pair dataset).

Based on proven patterns from HuggingFace Cookbook, NVIDIA SDG pipeline, and Red Hat's 2026 guide.

## In Scope

- Synthetic QA generation from existing chunks via Groq
- Three-agent quality filtering (groundedness, standalone, relevance)
- JSONL output with ground-truth chunk mappings
- Evaluation notebook computing IR metrics per strategy

## Out of Scope

- End-to-end RAG evaluation (no generation metrics like faithfulness)
- Human expert annotation (can be added later as a refinement pass)
- Persisting dataset to the database (stays as JSONL file)
- RAGAS/DeepEval framework integration

## Dataset Format

**Format**: JSONL at `data/eval_dataset.jsonl`

```json
{
  "id": "eval_001",
  "question": "How does one establish mindfulness of breathing?",
  "reference_answer": "One sits cross-legged, sets mindfulness to the fore...",
  "reference_contexts": ["<full text of the source chunk>"],
  "chunk_ids": ["uuid-abc123"],
  "source_document_id": 42,
  "metadata": {
    "question_type": "practical",
    "groundedness_score": 5,
    "standalone_score": 4,
    "relevance_score": 5,
    "difficulty": "medium"
  }
}
```

## Question Type Distribution (~100 pairs)

| Type | Count | Description |
|------|-------|-------------|
| Factual | 25 | Single-chunk lookup ("In which sutta...?") |
| Conceptual | 25 | Requires understanding ("What is the relationship between...?") |
| Practical | 25 | Practice-oriented ("How does one develop...?") |
| Cross-textual | 15 | Spans multiple documents |
| Pali-specific | 10 | Uses Pali terminology |

## Generation Pipeline

### Step 1: Chunk Sampling (~200 chunks)

- Load all chunks from `chunks` table via SQLAlchemy
- Stratified sampling across documents to ensure coverage of all 4 Nikayas
- Group by parent `document_id`, sample proportionally
- Target: ~200 diverse chunks (to yield ~100 after filtering)

### Step 2: Question + Answer Generation

For each sampled chunk, call Groq:

```
Your task is to write a question and answer given a passage from Buddhist scripture.

Requirements:
- The question should be answerable from the passage
- Phrase it as a real practitioner or student might ask (not "according to the passage...")
- The answer should be concise and grounded in the passage text
- Classify the question type: factual, conceptual, practical, cross_textual, or pali_specific

Context: {chunk_text}

Reply with valid JSON:
{"question": "...", "answer": "...", "question_type": "..."}
```

Rate limiting: 30 req/min on free tier → ~7 minutes for 200 chunks.

### Step 3: Quality Filtering (3 critique agents)

Three separate Groq calls per QA pair, each scoring 1-5:

1. **Groundedness**: "Is this question answerable from the given context?"
2. **Standalone**: "Can this question be understood without seeing the source passage?"
3. **Relevance**: "Would a meditation practitioner realistically ask this question?"

Filter threshold: keep only pairs scoring >= 4 on ALL three.
Expected yield: ~50-60% pass rate → ~100-120 pairs from 200 raw.

### Step 4: Deduplication

- Embed all generated questions using Voyage AI (already available)
- Remove pairs where question cosine similarity > 0.9

### Step 5: Export

- Write to `data/eval_dataset.jsonl`
- Print summary stats (count per question type, avg scores)

### API Budget (Groq free tier)

| Step | Calls | Est. tokens |
|------|-------|-------------|
| QA Generation | 200 | ~60K |
| Filtering (3 agents × 200) | 600 | ~30K |
| **Total** | **800** | **~90K** |

Fits within daily limits (1,000 requests, 100K tokens).

## Evaluation Metrics

The eval dataset enables computing standard IR metrics per retrieval strategy:

| Metric | What it measures |
|--------|-----------------|
| Recall@K (K=5,10) | Was the ground-truth chunk in the top K results? |
| Precision@K (K=5) | What fraction of retrieved chunks are relevant? |
| MRR | Average reciprocal rank of first relevant result |
| NDCG@K | Rank-weighted relevance quality |
| Hit Rate@K | Binary: at least one relevant chunk in top K? |

### Evaluation Flow

```
eval_dataset.jsonl (100 QA pairs with ground-truth chunk_ids)
     │
     ▼
For each question, run all 4 retrieval strategies
     │
     ▼
Compare retrieved chunk UUIDs against ground-truth chunk_ids
     │
     ▼
Compute Recall@5, Precision@5, MRR, NDCG@5, Hit Rate per strategy
     │
     ▼
Summary table + visualization comparing all 4 strategies
```

### Multi-chunk Ground Truth

For cross-textual questions, the generating chunk is the primary ground truth. Optionally expand by running Voyage AI similarity search and adding chunks with cosine similarity > 0.85 to the ground truth set.

### Output

- Comparison table: Strategy × Metric
- Per-question-type breakdown
- Visualization: bar charts + box plots

## Dependencies

No new dependencies required. Uses existing:
- `groq` (already in pyproject.toml)
- `sqlalchemy` (database access)
- `langchain-voyageai` (deduplication embeddings)
- `pandas` (analysis)
- `matplotlib` (visualization)

New env var: `GROQ_API_KEY` (already set up from existing eval notebook).

## Research Sources

- HuggingFace RAG Evaluation Cookbook
- NVIDIA SDG Pipeline for RAG Evaluation
- Red Hat — Synthetic Data for RAG Evaluation (2026)
- RAGAS GitHub Issues (#662, #1244, #1660, #2274) — informed decision to avoid RAGAS TestsetGenerator
- Know Your RAG (COLING 2025) — dataset taxonomy and generation strategies
- MufassirQAS — RAG evaluation for religious texts
