# Design: Eval-Gated Retrieval Strategy

**Date**: 2026-07-13
**Status**: Approved
**Author**: Himanshu (with Claude)
**Scope**: Evaluation strategy for retrieval + the extensibility model that lets retrieval grow
from simple vector search to enrichment-backed and agentic retrieval, with every step gated by
eval numbers.

---

## 1. Relationship to prior decisions

This doc **builds on** and does not relitigate:

- [2026-02-28 Eval Dataset Design](2026-02-28-eval-dataset-design.md) — approved but never
  executed. Revived here with three upgrades (§4). Its core choices stand: custom pipeline over
  RAGAS/DeepEval, JSONL dataset, chunk-UUID ground truth, IR metrics.
- [2026-07-10 Architecture Hardening](2026-07-10-architecture-hardening-retrieval-foundations-design.md) —
  D6/G6 (formal retrieval ports) is the seam this design plugs adapters into.
- [enrichment-layer-design.md](enrichment-layer-design.md) — concepts/summaries/graph become
  Phase 3 of the capability ladder here; its Milestone 5 ("the number that justifies the layer")
  is generalized into this doc's operating principle.

**Decision recap from brainstorming (2026-07-13):**
- First deliverable is the **Python framework + eval loop**, not an HTTP service. FastAPI comes
  later as a thin layer over proven strategies.
- Approach: **eval-gated capability ladder** (chosen over framework-first and
  error-analysis-only).
- Corpus: a few nikayas are ingested; ingest more, then freeze an eval corpus.

## 2. Operating principle

> Every retrieval capability is an adapter behind one port, and every adapter earns its place
> with numbers from a fixed eval harness.

The eval harness is the first deliverable because it is the instrument that turns every later
question — reranker? query expansion? concept tags? graph? agent? — into a measurement instead
of a vibe. A new strategy is promoted to default only if it beats the incumbent on primary
metrics without materially regressing any segment.

## 3. Research findings this design encodes

From Hamel Husain & Shreya Shankar's [LLM Evals FAQ](https://hamel.dev/blog/posts/evals-faq/)
(Jan 2026) and the surrounding literature:

1. **Error analysis is the core activity.** Look at real traces, open-code failures, group into
   a taxonomy (axial coding), iterate to saturation. Everything else derives from it.
2. **Separate retrieval evals from generation evals.** Retrieval → classic IR metrics
   (Recall@k, MRR, NDCG) against query↔chunk ground truth; synthetic pairs are the accepted
   bootstrap. Generation → domain-specific binary judges built only for *persistent* failure
   modes surfaced by error analysis.
3. **Binary pass/fail with critiques, never Likert scales.** Applies to critique agents in
   dataset generation and to LLM judges.
4. **Validate LLM judges against human labels** (TPR/TNR on a held-out labeled set, ~100
   examples) before trusting them.
5. **Avoid generic metric dashboards** (off-the-shelf "faithfulness"/"helpfulness" scores) —
   false confidence. The 2026-02-28 decision to skip RAGAS remains correct.
6. **Synthetic queries via structured dimensions** (persona × question type × register), not
   generic "write a question" prompts. Known pitfall: questions generated *from* chunks share
   the chunks' vocabulary and inflate retrieval scores; real queries are shorter and use
   layperson vocabulary.
7. **CI gets cheap deterministic checks only.** Full eval runs are a local command executed
   before/after retrieval changes; results are versioned artifacts.
8. **Solo maintainer = "benevolent dictator" labeler** — a recommended setup, not a compromise.

Agentic-RAG literature (LangGraph docs, Adaptive-RAG patterns, agentic RAG surveys): retrieval
strategies exposed as tools, router + grader + rewrite loops — but only after simple retrieval
is measured; reranking and hybrid tuning are the low-risk/high-return first upgrades.

## 4. Phase 0 — Freeze an eval corpus

- Ingest the remaining target nikayas (goal: DN, MN, SN, AN complete in Sujato English).
- Declare **eval corpus v1**: snapshot the set of document IDs + chunk UUIDs it contains
  (a small JSON manifest committed alongside the dataset).
- Ground truth is anchored at **two levels**:
  - **chunk UUID** — primary, used by IR metrics;
  - **sutta UID** (e.g., `mn10`) — stable across re-chunking; a future re-chunk means
    re-mapping the dataset (regenerate chunk-level truth from sutta-level anchors), not losing it.
- Re-chunking invalidates chunk-level ground truth *by design*. The dataset is regenerable by
  script — the "derived data is a cache, not truth" principle applies to eval data too. The
  hand-written seed set (§5) maps to sutta UIDs and always survives.

## 5. Track 1 — Retrieval eval harness (`evals/` package)

Revives the 2026-02-28 design with three upgrades:

**Upgrade 1 — dimension-based generation.** Each synthetic question is generated from a sampled
chunk *and* a dimension tuple:

| Dimension | Values |
|---|---|
| question_type | factual, conceptual, practical, cross_textual, pali_specific (existing taxonomy) |
| persona | new meditator, experienced practitioner, scholar |
| vocabulary register | **colloquial** (no canonical/Pali vocabulary) vs **canonical** |

The colloquial register is the critical one for this corpus: practitioners say "why am I
restless during meditation," the texts say *uddhacca-kukkucca*. Colloquial questions are the
honest test of the vocabulary gap that the enrichment layer exists to close.

**Upgrade 2 — binary critics.** Keep the three critique agents (grounded in the chunk /
standalone / realistic for a practitioner) but each returns **pass/fail + a one-line critique**,
not 1–5 scores. Keep only pairs passing all three.

**Upgrade 3 — hand-written seed set.** ~20–30 questions Himanshu would genuinely ask, mapped to
the sutta(s) that answer them (`data/evals/manual_seed.jsonl`). Highest-value rows; synthetic
data scales around them, never replaces them.

**Module layout** (repeatable CLIs, not notebooks):

```
evals/
├── __init__.py
├── dataset.py     # Pydantic models, JSONL load/validate, corpus manifest check
├── generate.py    # CLI: stratified chunk sampling → QA gen via LLMClient →
│                  #      binary critics → embedding dedup → data/evals/retrieval_v1.jsonl
├── metrics.py     # recall@k, precision@k, MRR, NDCG@k, hit_rate — pure functions
├── run.py         # CLI: dataset × every registered retrieval strategy → results;
│                  #      logs runs to Langfuse; report keyed by git hash + config snapshot
└── report.py      # Strategy × Metric table + per-segment breakdown (question_type, register)
```

**Primary metrics**: Recall@5, MRR. Secondary: NDCG@10, Hit-rate@5.

**Segments drive decisions.** The report always breaks metrics down by question_type and
vocabulary register. Interpretations:

- colloquial recall low → invest in query expansion / concept tags (Phase 2/3);
- cross_textual recall low → invest in summaries / graph (Phase 3);
- canonical-only wins → chunking/embedding is fine, vocabulary bridging is the gap.

**Execution model**: `poetry run python -m evals.run` locally before/after any retrieval or
ingestion change. Results written to `data/evals/results/<git-sha>-<timestamp>.json` and logged
to Langfuse. Not run in CI; CI keeps unit tests (metrics functions, dataset validation,
generation smoke test with `FakeLLMClient`).

## 6. Track 2 — Generation quality via error analysis

No generic faithfulness dashboards. Instead:

1. The RAG playground already traces every query/answer to Langfuse. Add a **thumbs up/down +
   free-text note** widget in the playground, recorded as Langfuse scores on the trace.
2. Periodically (roughly monthly, or after ~50–100 new traces): export traces, **open-code**
   failures (free-form notes per trace), **axial-code** into a failure taxonomy. The taxonomy is
   a living doc: `docs/evals/FAILURE_TAXONOMY.md`.
3. Build a **binary LLM judge only for failure modes that persist** across iterations. Validate
   each judge against Himanshu's own labels (TPR/TNR on a held-out set) before trusting it.
   Judges live in `evals/judges/` and run in the same harness.

## 7. Extensible retrieval framework

Formalize the `Retriever` port in `core/interfaces.py` (per the 07-10 doc's D6):

```python
class Retriever(Protocol):
    name: str
    def retrieve(self, query: str, k: int = 5) -> list[SearchResult]: ...
```

- The existing four strategies (similarity, MMR, threshold, hybrid RRF) become registered
  adapters wrapping `RetrievalEngine` internals.
- Future capabilities compose as **decorators/adapters, never rewrites**:

```
QueryExpansionRetriever(inner)         # Phase 2 — rewrite/expand query before inner retrieval
RerankedRetriever(inner, reranker)     # Phase 2 — e.g., Voyage rerank over inner's fetch_k pool
ConceptTagRetriever                    # Phase 3 — query→concept linking → chunk_concepts
SummaryRetriever                       # Phase 3 — multi-level (chunk + summary) vector search
GraphRetriever                         # Phase 3 — concept graph expansion (enrichment plan §6)
LangGraph agent                        # Phase 4 — retrievers exposed as tools
```

- **One registry** (name → factory) is consumed by the Streamlit playground, the eval harness
  (which iterates all registered strategies), and the future FastAPI layer.
- **Promotion rule**: a new adapter becomes the default strategy only if it beats the incumbent
  on Recall@5 and MRR without materially regressing any segment.

## 8. Capability ladder

| Phase | Deliverable | Gate |
|---|---|---|
| 0 | Ingest remaining nikayas; freeze eval corpus v1 (manifest) | — |
| 1 | `evals/` harness + dataset v1 (manual seed + synthetic) + **baseline report for the existing 4 strategies** | The unlock — first informed decision |
| 2 | Reranker, query rewrite/expansion, hybrid-weight tuning — each as an adapter | Each must beat the Phase-1 baseline |
| 3 | Enrichment layer per [enrichment-layer-design.md](enrichment-layer-design.md): concepts/tags, summaries, graph retrieval | Graph/summary retrieval must beat the Phase-2 winner |
| 4 | LangGraph agent (retrievers as tools) + thin FastAPI exposing winning strategies | End-to-end eval incl. unanswerable + multi-hop question sets |

## 9. Testing & error handling

- `evals/metrics.py` — pure functions, exhaustively unit-tested (known-answer fixtures).
- Dataset generation — smoke-tested with `FakeLLMClient`; every LLM call returns
  Pydantic-validated JSON with one retry on validation failure, then dead-letter (same
  discipline as the enrichment plan).
- Eval runner — a per-question failure is reportable data (`error` field in results), never a
  crashed run.
- Harness integration test against the seeded test DB (existing pattern in `tests/`).

## 10. Not doing (YAGNI)

- RAGAS/DeepEval integration (re-affirmed).
- FastAPI service now.
- Re-embedding or new chunk UUIDs outside of deliberate re-chunking events.
- Likert scales anywhere.
- Generic judge metrics ("helpfulness", "coherence", BERTScore/ROUGE).
- Full eval runs in CI.
- Agent frameworks before simple retrieval is measured.

## 11. Sources

- [LLM Evals FAQ — Hamel Husain & Shreya Shankar](https://hamel.dev/blog/posts/evals-faq/)
- [Binary vs Likert — Evals FAQ](https://hamel.dev/blog/posts/evals-faq/why-do-you-recommend-binary-passfail-evaluations-instead-of-1-5-ratings-likert-scales.html)
- [Evals, error analysis, and better prompts — Lenny's Newsletter interview](https://www.lennysnewsletter.com/p/evals-error-analysis-and-better-prompts)
- [A complete guide to RAG evaluation — Evidently AI](https://www.evidentlyai.com/llm-guide/rag-evaluation)
- [RAG Evaluation Metrics: Recall@K, MRR — LangCopilot](https://langcopilot.com/posts/2025-09-17-rag-evaluation-101-from-recall-k-to-answer-faithfulness)
- [Agentic RAG with LangGraph — LangChain docs](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- [Agentic RAG survey (arXiv 2501.09136)](https://arxiv.org/pdf/2501.09136)
- Prior in-repo research: [2026-03-22 RAG Query Layer Framework Research](2026-03-22-rag-query-layer-framework-research.md), [2026-02-28 Eval Dataset Design](2026-02-28-eval-dataset-design.md)
