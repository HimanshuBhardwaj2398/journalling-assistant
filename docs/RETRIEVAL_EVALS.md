# Evaluating Retrieval Before Trusting It: Architecture of a RAG Eval Harness

**Status**: Living document (baseline v1 complete, 2026-07-16)
**Code**: [`evals/`](../evals/) · **Data**: [`data/evals/`](../data/evals/) · **Design history**: `docs/plans/2026-07-13-retrieval-eval-strategy-design.md` (local)

This document describes the architecture and methodology of the retrieval evaluation
harness for the meditation-texts RAG system: how the synthetic eval dataset is
generated, how evals are executed, which metrics we compute, and — most importantly —
*why* each choice was made, with references to the supporting literature. It is written
to double as the source material for a blog post.

---

## 1. The problem: retrieval quality is invisible until you measure it

The system is a semantic search layer over early Buddhist texts (the Pali Canon in
Bhikkhu Sujato's English translation). Texts are chunked, embedded with Voyage AI
(`voyage-3.5`), and stored in Postgres/pgvector. Four retrieval strategies exist:

| Strategy | Mechanism |
|---|---|
| `similarity` | Plain cosine similarity top-k over chunk embeddings |
| `mmr` | Maximal Marginal Relevance — diversity-reweighted top-k over a `fetch_k=20` candidate pool ([Carbonell & Goldstein, 1998]) |
| `threshold` | Similarity top-k with a fixed minimum score cutoff (0.5) |
| `hybrid` | Reciprocal Rank Fusion of the vector ranking and a Postgres full-text (`ts_rank`) keyword ranking, `rrf_k=60` ([Cormack et al., 2009]) |

Which one should be the default? Should we add a reranker? Query expansion? A knowledge
graph? Every one of those questions is unanswerable without a fixed measurement
instrument. So the harness came first, encoded as an operating principle:

> **Every retrieval capability is an adapter behind one port, and every adapter earns
> its place with numbers from a fixed eval harness.**

This is the *eval-gated capability ladder*: a new strategy is promoted to default only
if it beats the incumbent on the primary metrics **without materially regressing any
segment** (§7). The alternative — shipping a reranker because rerankers are supposed to
help — is how RAG systems accumulate unmeasured complexity.

A second principle, taken from Hamel Husain & Shreya Shankar's [LLM Evals
FAQ][evals-faq]: **separate retrieval evals from generation evals.** Retrieval is a
ranking problem with decades of established IR methodology (binary relevance judgments,
Recall@k, MRR, NDCG). Generation quality is a different problem requiring error
analysis and domain-specific judges. Conflating them — as generic "RAG score"
dashboards do — produces numbers nobody can act on. This harness evaluates retrieval
only; generation evals are a separate track driven by error analysis on real traces.

## 2. Architecture overview

The harness is a set of small CLIs (not notebooks) in the `evals/` package:

```
                    ┌──────────────────────────────────────────────┐
                    │ Phase 0: freeze corpus                        │
   Postgres corpus  │  evals/corpus.py → corpus_manifest_v1.json    │
   (docs + chunks)  │  (per-doc chunk-UUID md5 → drift detection)   │
                    └──────────────┬───────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────────────────┐
                    │ Dataset generation                            │
                    │  evals/generate.py                            │
                    │  stratified chunk sampling                    │
                    │   → dimension deck (qtype × persona × reg.)   │
                    │   → LLM QA generation                         │
                    │   → 3 binary critics (pass/fail + critique)   │
                    │   → embedding near-dup removal                │
                    │   → merge with manual seed set                │
                    │  = data/evals/retrieval_v1.jsonl  (git truth) │
                    └──────────────┬───────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
   ┌──────────▼─────────┐ ┌───────▼────────┐  ┌────────▼─────────┐
   │ evals/sync.py       │ │ evals/run.py   │  │ evals/report.py  │
   │ upsert to Langfuse  │ │ dataset ×      │  │ Strategy × Metric│
   │ hosted dataset      │ │ every strategy │  │ tables + segment │
   │ (display copy only) │ │ → IR metrics   │  │ breakdowns       │
   └─────────────────────┘ │ → results JSON │  └──────────────────┘
                           │ → Langfuse     │
                           │   experiments  │
                           └────────────────┘
```

Module responsibilities:

| Module | Role |
|---|---|
| [`evals/dataset.py`](../evals/dataset.py) | Pydantic row schema, JSONL load/validate |
| [`evals/corpus.py`](../evals/corpus.py) | Corpus manifest: freeze + drift verification |
| [`evals/generate.py`](../evals/generate.py) | Synthetic QA generation with binary critics |
| [`evals/metrics.py`](../evals/metrics.py) | Pure IR metric functions (unit-tested) |
| [`evals/run.py`](../evals/run.py) | Runner: dataset × every registered strategy |
| [`evals/sync.py`](../evals/sync.py) | Push dataset to Langfuse (JSONL stays truth) |
| [`evals/report.py`](../evals/report.py) | Markdown comparison tables |

Everything downstream of the corpus is **regenerable by script** — the "derived data is
a cache, not truth" principle applies to eval data too. The one exception is the
hand-written seed set, which is anchored so that it survives any re-processing (§4).

## 3. Freezing the corpus: evals need a fixed target

An eval score is only meaningful relative to a fixed corpus. If documents are added or
re-chunked between two runs, the numbers aren't comparable and chunk-level ground truth
silently dangles. The harness makes this failure loud instead of silent:

- `evals/corpus.py` snapshots every completed document as `(document_id, sutta_uid,
  chunk_count, md5(sorted chunk UUIDs))` into a committed JSON manifest.
- `evals/run.py` verifies the live database against the manifest before every run and
  **refuses to run on drift** (override: `--allow-drift`, for exploratory runs only).
- The md5-of-UUIDs trick detects re-chunking per document without storing every UUID.

Corpus v1: 20 documents / 124 chunks (partial DN + MN — deliberately small; see
limitations in §8).

## 4. Ground truth: two anchor levels

Each eval row carries the question plus ground truth at up to three granularities, and
the runner resolves them in priority order:

1. **`chunk_uuids`** — the exact chunk(s) the question was generated from. Primary
   anchor for synthetic rows; enables chunk-level IR scoring, the strictest test.
2. **`source_document_ids` / `sutta_uids`** — document-level truth. Sutta UIDs (e.g.
   `mn10`) are SuttaCentral's stable identifiers: they survive re-chunking,
   re-embedding, even re-ingestion. The manual seed set is anchored *only* at this
   level for exactly that reason.

This two-level design encodes a lifecycle decision: **re-chunking invalidates
chunk-level ground truth by design**, and that's fine — the synthetic dataset is
regenerated by script against the new chunks, while the human-written rows (the
highest-value ones) persist because suttas don't change identity when chunks do.

Document-level scoring has one subtlety that produced our first real bug: many chunks
map to one document, so a result list can contain the same document id several times.
Scoring that list naively lets repeated hits accumulate DCG **past the ideal, yielding
NDCG > 1.0**. The fix (commit `e9e7595`) deduplicates ids keeping first occurrence
before scoring. Impossible metric values are a gift — validate metric ranges early.

## 5. Dataset generation: dimensions, critics, dedup

The obvious way to generate synthetic eval data — "here's a passage, write a question
about it" — produces questions that share the passage's exact vocabulary. Retrieval
over such questions is nearly a string-matching exercise, and scores inflate
accordingly. This is the central known pitfall of synthetic IR data (the same insight
that motivates query-generation-with-filtering pipelines like [InPars][inpars] and
[Promptagator][promptagator], and the LLM-judged data pipelines in [ARES][ares]).

Our corpus makes the pitfall vicious: the texts say *uddhacca-kukkucca*; a real user
says "why am I restless during meditation." A dataset drawn only from the texts'
vocabulary would measure a system we don't actually need to build. The generation
pipeline addresses this in four stages.

### 5.1 Stratified chunk sampling

Chunks (minimum 300 chars, completed documents only) are sampled proportionally per
nikāya (text collection) with a seeded RNG, so no collection dominates and runs are
reproducible.

### 5.2 Dimension-conditioned generation

Every sampled chunk is paired with a tuple from a deterministic **dimension deck**
(seeded, so dataset regeneration is stable):

| Dimension | Values | Distribution |
|---|---|---|
| `question_type` | factual / conceptual / practical / cross_textual / pali_specific | 25 / 25 / 25 / 15 / 10 % |
| `persona` | new meditator / experienced practitioner / scholar | round-robin |
| `register` | **colloquial** / **canonical** | alternating (pali_specific forces canonical) |

The register dimension is the one that matters most. The colloquial prompt instructs:
*"Do NOT use any Pali words or technical Buddhist terms, even if the passage uses them
— phrase it the way a regular person would."* Colloquial questions are the honest test
of the vocabulary gap between practitioners and canonical texts — the gap the future
enrichment layer (concept tags, summaries) exists to close. Without this dimension,
that entire investment would be unmeasurable.

The generation prompt itself enforces three rules: answerable from the passage; never
mention "the passage/text/author"; must make sense standalone.

### 5.3 Binary critics, not Likert scores

Each candidate QA pair is judged by three independent LLM critics:

| Critic | Question it answers |
|---|---|
| `grounded` | Can this question be answered from the passage alone? |
| `standalone` | Is it fully understandable without seeing the passage? |
| `realistic` | Would a real practitioner plausibly ask this — genuine query, not quiz item? |

Each returns **pass/fail plus a one-line critique** — never a 1–5 score. A pair must
pass all three. The binary choice follows the Evals-FAQ argument ([why binary over
Likert][binary]): pass/fail forces a definable standard and is verifiable, whereas
Likert points ("what distinguishes a 3 from a 4?") are ill-defined, drift between
runs, and average into numbers with no decision content. The one-line critique
preserves the diagnostic signal a scalar would have destroyed — it told us, for
example, that the standalone critic over-rejects (§7, caveats).

This critic structure is the same *generate-then-filter* pattern shown to matter in
[Promptagator][promptagator] (round-trip filtering) and [ARES][ares] (judge-filtered
synthetic queries): the generator is allowed to be mediocre because the filter defines
the bar.

### 5.4 Near-duplicate removal + LLM-call discipline

Surviving questions are embedded (`voyage-3.5`) and greedily deduplicated at cosine ≥
0.9, so one over-represented theme can't occupy ten rows. Every LLM call in the
pipeline returns JSON parsed with **one retry, then dead-letter** (row skipped and
logged) — free-text parsing is banned, and a malformed generation can never corrupt the
dataset or crash the run.

### 5.5 The manual seed set

Alongside the synthetic rows lives `manual_seed.jsonl`: questions the maintainer would
*genuinely ask*, mapped by hand to the sutta(s) that answer them. These are the
highest-value rows — real information needs, immune to the synthetic-vocabulary
artifact — and synthetic data scales around them, never replaces them. (This is the
"benevolent dictator" labeling model the Evals FAQ recommends for solo maintainers.)

Dataset v1 funnel: **116 generated → 35 passed critics → 20 after dedup, + 3 seed
rows = 23 rows** (21 scorable against corpus v1).

## 6. Executing the evals

`poetry run python -m evals.run` executes, for every strategy in the retrieval
registry: verify corpus manifest → resolve sutta-uid anchors to document ids → retrieve
`k=max(k_values)` results per question → score → aggregate.

Design decisions worth calling out:

- **One registry, three consumers.** Strategies register once
  ([`retrieval/registry.py`](../retrieval/registry.py)) behind a two-method `Retriever`
  port; the eval harness, the Streamlit playground, and the future API all iterate the
  same registry. Adding a strategy makes it automatically evaluated.
- **Per-row failures are data, not crashes.** A strategy throwing on one question is
  recorded in the report's `errors` list; the run continues.
- **Results are versioned artifacts**: `data/evals/results/<git-sha>-<timestamp>.json`
  with git SHA, timestamp, dataset path, and per-row scores. Baselines referenced in
  docs get committed. Two runs are comparable iff same dataset + same manifest.
- **Langfuse as a lens, not a store.** When Langfuse keys are configured, each strategy
  runs as a hosted *dataset experiment* (one run per strategy, per-row metrics attached
  as scores), which gives a free side-by-side comparison UI. But ground truth is always
  read from the local rows, the same scoring functions serve both paths, and the
  results JSON is written either way. **The JSONL in git stays the source of truth**;
  the hosted copy is display. `evals/sync.py` upserts by row id, so re-syncing is
  idempotent.
- **Not in CI.** Full runs hit the embedding API and the database; they run locally
  before/after any retrieval or ingestion change. CI keeps the cheap deterministic
  layer: metric unit tests, dataset validation, generation smoke test with a fake LLM
  client. (Evals FAQ: "CI gets cheap deterministic checks only.")

## 7. Metrics: definitions and why these four

All metrics use **binary relevance** (a retrieved id is in the ground-truth set or it
isn't) over ranked lists, implemented as pure functions in
[`evals/metrics.py`](../evals/metrics.py). Binary relevance is the honest choice here:
ground truth comes from generation provenance (this chunk produced this question), not
from graded human judgments, so inventing relevance grades would be false precision.

Let $R$ be the relevant-id set and $r_1, r_2, \ldots$ the retrieved ids in rank order.

**Recall@k** — $\frac{|\{r_1..r_k\} \cap R|}{|R|}$. *Primary metric.* In a RAG system
the retriever's job is to get the answer-bearing chunk into the context window at all;
the LLM can tolerate some noise around it, but it cannot recover a chunk that was never
retrieved. Recall@k measures exactly that ceiling. We report k=5 (roughly a context
window's worth of chunks) and k=10.

**MRR (Mean Reciprocal Rank)** — $\frac{1}{|Q|}\sum_q \frac{1}{\text{rank of first
relevant}}$ ([Voorhees, 1999], the TREC-8 QA track metric). *Primary metric.* Recall@5
is blind to position 1 vs position 5; MRR is the sharpest single number for "does the
best chunk surface first." Rank position matters beyond aesthetics: generation quality
degrades when relevant content sits in the middle of the context ([Liu et al., 2023,
"Lost in the Middle"][lost]), and any future reranker or agentic step will read from
the top down.

**NDCG@k** — $\frac{DCG@k}{IDCG@k}$ where $DCG@k = \sum_{i=1}^{k}
\frac{rel_i}{\log_2(i+1)}$ ([Järvelin & Kekäläinen, 2002]). *Secondary.* Where MRR
only sees the *first* relevant hit, NDCG rewards placing *all* relevant items high —
which matters precisely for the `cross_textual` questions whose answers span several
chunks or suttas. With binary relevance and a single gold item, NDCG collapses toward
MRR; its value here is for multi-anchor rows, and it's the standard headline metric of
IR benchmarks like [BEIR][beir], keeping our numbers externally interpretable.

**Hit-rate@k** — 1 if any relevant id appears in the top k, else 0. *Secondary.* The
bluntest and most explainable number ("in what fraction of questions did we find *a*
right chunk in the top 5?") — useful for communicating results, and identical to
Recall@k whenever a row has a single gold document, which the v1 numbers confirm.

Precision@k is implemented but not reported: with 1–2 relevant ids per row and k=5,
its ceiling is 0.2–0.4 and it adds no decision signal over recall at this dataset
shape.

**Why not end-to-end RAG metrics (RAGAS, faithfulness, answer relevance)?** Considered
and rejected, twice. Off-the-shelf composite scores ([RAGAS][ragas]) blur retrieval
and generation, hide *which* component failed, and generic "faithfulness" judges give
false confidence unless validated against human labels ([Evals FAQ][evals-faq]).
LLM-as-judge itself is a reasonable tool ([Zheng et al., 2023][mtbench]) — but the
plan is to build **binary judges only for failure modes that persist** in real traces,
and to validate each judge against human labels (TPR/TNR on a held-out set) before
trusting it.

### Segments drive decisions

Aggregate numbers pick a winner; **segment breakdowns pick the roadmap**. Every report
splits by `register` and `question_type`, with pre-committed interpretations:

| Signal | Decision it triggers |
|---|---|
| Colloquial recall ≪ canonical | Invest in query expansion / concept tags (vocabulary bridging) |
| `cross_textual` recall low | Invest in summaries / graph retrieval |
| Canonical-only wins everywhere | Chunking + embeddings are fine; bridging is the whole gap |

Committing to interpretations *before* seeing numbers is deliberate — it keeps the eval
from becoming a Rorschach test.

## 8. Baseline results (v1) and what they taught us

Run `e9e7595`, corpus v1 (20 docs / 124 chunks), 21 scored rows, k ∈ {5, 10}:

| strategy | MRR | recall@5 | ndcg@5 | hit_rate@5 |
|---|---|---|---|---|
| **hybrid (RRF)** | **0.5571** | **0.8571** | **0.6335** | 0.8571 |
| similarity | 0.5214 | 0.8571 | 0.6064 | 0.8571 |
| mmr | 0.4147 | 0.5714 | 0.4502 | 0.5714 |
| threshold@0.5 | 0.3254 | 0.4286 | 0.3520 | 0.4286 |

Findings:

1. **Hybrid wins and stays the default** — equal recall to pure vector search but
   better MRR/NDCG, i.e. the keyword signal improves *ordering*. Consistent with the
   general result that reciprocal rank fusion of lexical + dense rankings is a cheap,
   robust win ([Cormack et al., 2009]).
2. **The vocabulary gap is real and now has a number.** Hybrid on canonical questions:
   recall@5 = 1.0, MRR = 0.76. On colloquial: recall@5 = 0.75, MRR = 0.41. This is the
   register dimension doing its job — Phase 2 attacks colloquial first (query
   expansion), exactly as the design predicted it would need to.
3. **Threshold@0.5 is broken for colloquial phrasing** (recall@5 = 0.25, frequent empty
   result sets): a fixed similarity cutoff tuned on canonical vocabulary filters out
   legitimate everyday-language matches.
4. **MMR trades too much recall for diversity** at this corpus size.

Caveats, stated as loudly as the results: smoke-scale corpus (2 nikāyas, partial);
21 rows, so segment cells are small; the `standalone` critic over-rejects (~70% kill
rate, mostly "requires context") and needs tuning before dataset v2; results before
the NDCG dedup fix (`e9e7595`) are not comparable.

## 9. Deliberate non-goals

Recorded so future-us knows these were choices, not oversights:

- **No RAGAS/DeepEval** — custom pipeline preferred (§7).
- **No Likert scales anywhere** — binary + critique only.
- **No generic judge metrics** ("helpfulness", "coherence", BERTScore/ROUGE).
- **No full eval runs in CI** — local instrument, versioned artifacts.
- **No agent frameworks before simple retrieval is measured** — agentic RAG (routers,
  graders, rewrite loops; see the [agentic RAG survey][agentic-survey]) arrives in
  Phase 4, gated on end-to-end evals including unanswerable and multi-hop sets.

## 10. Current limitations & next steps

- **Scale**: 21 rows over 124 chunks is a baseline instrument, not a benchmark. Next:
  ingest the remaining nikāyas, freeze corpus v2, regenerate at `--target 150`.
- **Critic calibration**: relax the `standalone` critic; spot-check a critic sample
  against human judgment (the same validate-your-judge discipline of §7).
- **Seed set growth**: 3 → 20–30 hand-written questions; two seed rows currently skip
  because their suttas aren't ingested yet.
- **Phase 2 adapters**: reranking and query expansion as decorator retrievers
  (`RerankedRetriever(inner)`, `QueryExpansionRetriever(inner)`), each judged by this
  harness against the hybrid baseline.
- **Generation-side evals**: thumbs-up/down in the playground → trace export → open
  coding → failure taxonomy → binary judges for persistent failure modes only.

## References

- Hamel Husain & Shreya Shankar. *LLM Evals FAQ* (2026). <https://hamel.dev/blog/posts/evals-faq/> — error analysis as the core activity; retrieval/generation separation; binary judgments; judge validation.
- Järvelin, K. & Kekäläinen, J. *Cumulated Gain-Based Evaluation of IR Techniques*. ACM TOIS 20(4), 2002. — NDCG.
- Voorhees, E. *The TREC-8 Question Answering Track Report*. TREC, 1999. — MRR.
- Cormack, G., Clarke, C., & Buettcher, S. *Reciprocal Rank Fusion Outperforms Condorcet and Individual Rank Learning Methods*. SIGIR 2009. — RRF, used by the hybrid strategy.
- Carbonell, J. & Goldstein, J. *The Use of MMR, Diversity-Based Reranking for Reordering Documents and Producing Summaries*. SIGIR 1998. — MMR.
- Thakur, N. et al. *BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models*. NeurIPS 2021. <https://arxiv.org/abs/2104.08663> — NDCG@10 as the cross-domain IR standard.
- Liu, N. et al. *Lost in the Middle: How Language Models Use Long Contexts*. TACL 2024. <https://arxiv.org/abs/2307.03172> — why rank position matters for RAG.
- Bonifacio, L. et al. *InPars: Data Augmentation for Information Retrieval Using Large Language Models*. 2022. <https://arxiv.org/abs/2202.05144> — LLM-generated queries for IR training/eval.
- Dai, Z. et al. *Promptagator: Few-shot Dense Retrieval From 8 Examples*. ICLR 2023. <https://arxiv.org/abs/2209.11755> — generate-then-filter synthetic queries.
- Saad-Falcon, J. et al. *ARES: An Automated Evaluation Framework for Retrieval-Augmented Generation Systems*. NAACL 2024. <https://arxiv.org/abs/2311.09476> — synthetic queries + validated judges for RAG eval.
- Zheng, L. et al. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*. NeurIPS 2023. <https://arxiv.org/abs/2306.05685> — LLM-as-judge reliability and biases.
- Es, S. et al. *RAGAS: Automated Evaluation of Retrieval Augmented Generation*. 2023. <https://arxiv.org/abs/2309.15217> — the framework we evaluated and declined.
- Singh, A. et al. *Agentic Retrieval-Augmented Generation: A Survey*. 2025. <https://arxiv.org/abs/2501.09136> — Phase-4 patterns.
- Evidently AI. *A Complete Guide to RAG Evaluation*. <https://www.evidentlyai.com/llm-guide/rag-evaluation>

[evals-faq]: https://hamel.dev/blog/posts/evals-faq/
[binary]: https://hamel.dev/blog/posts/evals-faq/why-do-you-recommend-binary-passfail-evaluations-instead-of-1-5-ratings-likert-scales.html
[inpars]: https://arxiv.org/abs/2202.05144
[promptagator]: https://arxiv.org/abs/2209.11755
[ares]: https://arxiv.org/abs/2311.09476
[ragas]: https://arxiv.org/abs/2309.15217
[mtbench]: https://arxiv.org/abs/2306.05685
[beir]: https://arxiv.org/abs/2104.08663
[lost]: https://arxiv.org/abs/2307.03172
[agentic-survey]: https://arxiv.org/abs/2501.09136
[Cormack et al., 2009]: https://dl.acm.org/doi/10.1145/1571941.1572114
[Carbonell & Goldstein, 1998]: https://dl.acm.org/doi/10.1145/290941.291025
[Järvelin & Kekäläinen, 2002]: https://dl.acm.org/doi/10.1145/582415.582418
[Voorhees, 1999]: https://trec.nist.gov/pubs/trec8/papers/qa_report.pdf
