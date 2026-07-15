# Enrichment Layer Plan: Summaries, Concepts, and Graph

Status: Draft for discussion · Scope: Phase 3 (extends ROADMAP "GraphRAG API (Future)")

---

## 1. First principles

Start from the failure mode, not the technology.

**Why plain vector RAG falls short for this corpus.** A query like *"why am I feeling restless during meditation"* doesn't share vocabulary with the suttas. The texts say *uddhacca-kukkucca* (restlessness-and-remorse), one of the five hindrances. Vector similarity partially bridges this, but it retrieves isolated chunks — it cannot answer "what does the canon *as a whole* say about restlessness, its causes, and its antidotes," because that answer lives in the *relationships between* chunks scattered across four Nikāyas.

**The core insight.** Chunks are the wrong unit of knowledge for synthesis questions. Two kinds of derived data fix this:

1. **Summaries at higher abstraction levels** (sutta → vagga/section → theme). A question about "dealing with grief" is better answered by a theme-level summary that already integrates 15 suttas than by 5 raw chunks. This is the RAPTOR result: retrieving from the right abstraction level gave a 20% absolute accuracy gain on synthesis-style QA.
2. **An explicit concept graph.** *Restlessness → is-one-of → five hindrances → counteracted-by → samādhi practices*. Graph edges make multi-hop connections retrievable that embeddings only encode fuzzily. This is the GraphRAG insight, minus its cost problem (Microsoft GraphRAG burns ~610k tokens per global query; we take the cheap parts only).

**Design principle: derived data is a cache, not truth.** Every summary, concept, and edge must be (a) traceable to source chunks (citations preserved), (b) rebuildable from scratch (idempotent pipeline stage), (c) versioned by the model that generated it. This keeps the enrichment layer disposable — wrong extractions are a re-run, not a migration crisis.

**Sequencing decision (agreed):** corpus enrichment first, personal-memory layer second — but the schema anticipates the memory layer from day one, because "why am I feeling X" queries ultimately want to join *personal observations* against *corpus concepts*. Shared concept vocabulary is the bridge.

---

## 2. What gets built

Three derived-data types, all stored in Postgres alongside existing tables:

```
                    ┌─────────────────────────────────────┐
                    │            ENRICHMENT LAYER          │
 documents ──┐      │                                     │
             ├──►   │  concepts        (canonical nodes)  │
 chunks ─────┘      │  concept_edges   (typed relations)  │
                    │  chunk_concepts  (provenance links) │
                    │  summaries       (RAPTOR-lite tree) │
                    └─────────────────────────────────────┘
                                     │
                                     ▼
                     Retrieval: vector ∪ graph ∪ summary
```

**Concepts** — canonical entities: doctrinal terms (dukkha, anattā), practices (ānāpānasati, mettā), mental states (the hindrances, jhāna factors), persons (Sāriputta), similes. Pali term + English gloss + one-paragraph definition synthesized from the corpus itself.

**Concept edges** — small closed vocabulary of relation types. Resist the open-ended relation extraction that makes GraphRAG graphs noisy. Start with ~8: `is_a`, `part_of`, `causes`, `counteracts`, `precedes` (path/stage ordering), `supports`, `taught_via` (simile/parable), `related_to` (fallback). Each edge carries source chunk IDs as evidence.

**Summaries** — a shallow tree, not full RAPTOR clustering. Your chunks already carry header hierarchy in `chunk_metadata`, so use the *structural* hierarchy the canon gives us for free instead of embedding-space clustering: chunk → sutta summary → vagga/saṃyutta summary → Nikāya theme summaries. Each summary is embedded and lives in the same vector store, tagged with `level`, so retrieval can mix levels.

---

## 3. Schema (Postgres edge tables — agreed)

New Alembic migration, four tables. Sketch:

```sql
CREATE TABLE concepts (
    id           BIGSERIAL PRIMARY KEY,
    slug         TEXT UNIQUE NOT NULL,        -- 'uddhacca-kukkucca'
    pali_term    TEXT,
    english_term TEXT NOT NULL,
    definition   TEXT,                         -- synthesized, with citations
    concept_type TEXT NOT NULL,                -- doctrine|practice|mental_state|person|simile
    embedding_uuid TEXT,                       -- definition embedded in vector store
    model_version TEXT NOT NULL,               -- which LLM generated this
    created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE concept_edges (
    id           BIGSERIAL PRIMARY KEY,
    source_id    BIGINT REFERENCES concepts(id) ON DELETE CASCADE,
    target_id    BIGINT REFERENCES concepts(id) ON DELETE CASCADE,
    relation     TEXT NOT NULL,                -- closed vocabulary, CHECK constraint
    evidence_chunk_ids BIGINT[] NOT NULL,      -- provenance, always
    confidence   REAL,
    model_version TEXT NOT NULL,
    UNIQUE (source_id, target_id, relation)
);

CREATE TABLE chunk_concepts (                  -- many-to-many with provenance
    chunk_id     BIGINT REFERENCES chunks(id) ON DELETE CASCADE,
    concept_id   BIGINT REFERENCES concepts(id) ON DELETE CASCADE,
    salience     REAL,                         -- how central is the concept to the chunk
    PRIMARY KEY (chunk_id, concept_id)
);

CREATE TABLE summaries (
    id           BIGSERIAL PRIMARY KEY,
    scope_type   TEXT NOT NULL,                -- 'sutta' | 'section' | 'theme'
    document_id  BIGINT REFERENCES documents(id) ON DELETE CASCADE,
    source_chunk_ids BIGINT[] NOT NULL,
    parent_summary_id BIGINT REFERENCES summaries(id),  -- tree structure
    summary_text TEXT NOT NULL,
    embedding_uuid TEXT,                       -- lives in same vector store, tagged
    model_version TEXT NOT NULL,
    created_at   TIMESTAMPTZ DEFAULT now()
);
```

Graph traversal is a recursive CTE — no new infra:

```sql
WITH RECURSIVE neighborhood AS (
    SELECT id, source_id, target_id, relation, 1 AS depth
    FROM concept_edges WHERE source_id = :seed
    UNION ALL
    SELECT e.id, e.source_id, e.target_id, e.relation, n.depth + 1
    FROM concept_edges e JOIN neighborhood n ON e.source_id = n.target_id
    WHERE n.depth < 2
)
SELECT * FROM neighborhood;
```

**Architecture lesson worth internalizing here:** this is the "reconciliation over open extraction" pattern. Entity extraction without a canonical layer produces `restlessness`, `Restlessness`, `uddhacca`, and `agitation` as four nodes. The fix is a two-phase design: extract candidates per-chunk, then *reconcile* against the concepts table (embedding similarity + exact Pali match) before inserting. Same pattern as entity resolution in data engineering.

---

## 4. Pipeline: two new DAG stages

Extend the existing orchestrator (`ingestion/orchestrator.py`, `ingestion/stages.py`) — enrichment is just more stages after `EMBEDDING`:

```
... → EMBEDDING → CONCEPT_EXTRACTION → SUMMARIZATION → COMPLETED
```

**Stage: concept extraction** (per chunk, batched)
1. LLM call with structured output → `[{term, pali, type, salience}, ...]`
2. Reconcile each candidate against `concepts` (pgvector similarity on definition embedding + exact term match). New concept only above a distinctness threshold.
3. Insert `chunk_concepts` rows.
4. Second pass per document: propose edges between co-occurring concepts, LLM validates relation type from the closed vocabulary, insert with evidence chunk IDs.

**Stage: summarization** (bottom-up, uses `chunk_metadata` header hierarchy)
1. Group chunks by sutta (header hierarchy) → sutta summary (map step).
2. Group sutta summaries by vagga/section → section summary (reduce step).
3. Theme summaries: cluster section summaries by embedding (this is the only place clustering is needed), one theme summary per cluster.
4. Embed all summaries into the existing vector store with `level` metadata.

Both stages are idempotent: keyed on `(chunk_id, model_version)`, re-runs skip or replace.

**Structured output discipline:** every LLM call returns JSON validated against a Pydantic model, with one retry on validation failure, then dead-letter. Never parse free text. Ollama and Groq both support JSON-schema-constrained output.

---

## 5. Model and tooling choices (limited local GPU — agreed)

**Hybrid strategy — the honest math.** Corpus is ~43MB of PDFs, likely 15–30k chunks. Extraction + summarization is one LLM call per chunk plus reduce steps — call it 40–60M tokens total, one-time.

| Job | Runtime | Model | Why |
|-----|---------|-------|-----|
| Bulk corpus pass (one-time) | **Groq** (already in your stack) or DeepInfra | `llama-3.3-70b` / Qwen3-32B class | ~40–60M tokens at open-weights API pricing is a few dollars; a limited laptop GPU would grind for days |
| Incremental + experimentation | **Ollama local** | Qwen3-4B or Qwen3-8B (Q4 quant) | Free, private, fine for one-doc-at-a-time ingestion; 4B-class models are solid at extraction with tight JSON schemas |
| Personal-memory layer (later) | **Ollama local only** | same | Personal reflections should never leave the machine — this is where local inference actually matters, not just saves money |

**Provider abstraction:** one interface, two implementations. You already have `core/interfaces.py` and a strategy pattern from Sprint 2 — add an `LLMProvider` protocol (`extract_concepts()`, `summarize()`) with `GroqProvider` and `OllamaProvider`. Config-switchable per stage. This is the same inversion-of-control you used for chunking strategies.

**Tools, minimal set:**
- **Ollama** — local runtime, OpenAI-compatible API, handles quantization. Simplest choice; vLLM is for servers, skip it.
- **Pydantic + `instructor`** (or LangChain `with_structured_output`) — schema-validated LLM output. You already depend on LangChain; either is fine, `instructor` is lighter and worth knowing.
- **No graph framework.** LightRAG/nano-graphrag/Microsoft GraphRAG bring their own storage and bypass your schema, pipeline, and provenance model. Steal their *prompts and ideas* (LightRAG's dual-level retrieval, GraphRAG's entity-extraction prompt structure), keep your own architecture. For a learning-oriented project this is the right call anyway: the frameworks are ~2k lines of readable Python each — read them, don't adopt them.
- **Visualization:** export concept graph to `networkx` → `pyvis` HTML page in the Streamlit UI. Cheap and impressive.

---

## 6. Retrieval: how the derived data gets used

Query flow for the future RAG API (extends ROADMAP Phase 2):

1. **Concept linking:** embed the query, match against concept definitions → seed concepts (e.g., "restless" → *uddhacca-kukkucca*).
2. **Graph expansion:** 1–2 hop CTE from seeds → related concepts (hindrances, antidotes) → their top chunks via `chunk_concepts` ordered by salience.
3. **Multi-level vector search:** query against chunks *and* summaries; synthesis-flavored questions ("what does Buddhism say about...") naturally rank summaries higher, lookup questions rank chunks higher. No router needed initially — let similarity + a `level` boost decide.
4. **Merge + rerank** (RRF — reciprocal rank fusion — across the three lists), pass to response layer with citations flowing through from `evidence_chunk_ids` / `source_chunk_ids`.

This composes with the retrieval-strategy evaluation already in flight — graph-augmented retrieval becomes strategy #5 in that comparison, measured with the same LLM-as-judge harness.

---

## 7. Personal-memory layer (phase next, schema hooks now)

The "why am I feeling X" use case: user journals/queries accumulate; the system summarizes sessions into observations linked to corpus concepts ("user reports restlessness in evening sits" → *uddhacca-kukkucca*), so later research questions retrieve both canonical teaching *and* personal history.

- Landscape: **Graphiti (Zep)** — temporal knowledge graph, facts carry validity windows; **Mem0** — lighter vector+graph memory. On LongMemEval, Zep ~64% vs Mem0 ~49%, but Graphiti wants Neo4j. Recommendation: build a minimal version on the same Postgres pattern (`observations` table: text, timestamp, linked concept_ids, session_id) and borrow Graphiti's *temporal* idea — observations are facts with time bounds, "felt anxious (June)" can be superseded. Adopt Graphiti later only if this outgrows SQL.
- Hooks already in this design: shared `concepts` table, provenance arrays, local-only LLM policy for personal data.

---

## 8. Milestones

| # | Deliverable | Proves |
|---|-------------|--------|
| 1 | Migration + `LLMProvider` (Groq/Ollama) + concept extraction on **one document** (e.g., DN 22) | End-to-end extraction quality; prompt iteration loop |
| 2 | Reconciliation pass + edge extraction on 3–5 related suttas | Graph is clean (no duplicate nodes), edges make sense to *you* reading them |
| 3 | Sutta + section summaries for one Nikāya, embedded with `level` tags | Summary quality; retrieval mixing levels |
| 4 | Full corpus run via Groq; pyvis graph page in Streamlit | Scale + the demo moment |
| 5 | Graph-augmented retrieval as strategy #5 in existing eval harness | **The number that justifies the layer** |
| 6 | Personal observations MVP (local-only) | The original vision |

Milestone 5 is the honesty checkpoint: if graph+summary retrieval doesn't beat hybrid BM25+vector on your judge scores, the enrichment layer is decoration. Build the eval before scaling the corpus run.

## 9. Risks

- **Extraction noise compounds** — bad concepts → bad edges → bad retrieval. Mitigation: reconciliation phase, closed relation vocabulary, milestone 2 human review before scaling.
- **Small-model JSON reliability** — 4B models drift on complex schemas. Mitigation: one extraction task per call (concepts OR edges, never both), schema-constrained decoding, dead-letter queue.
- **Doctrinal nuance** — LLM summaries of suttas can flatten or distort teachings. Mitigation: summaries always cite sources; UI shows summary *and* underlying chunks; treat summaries as navigation aids, not authority.
- **Pali handling** — verify diacritics survive the pipeline (they should; worth a test).

## 10. Reading list

- RAPTOR paper (arXiv 2401.18059) — hierarchical summarization for retrieval; our §2 is a structural-hierarchy simplification of it
- Microsoft GraphRAG paper (arXiv 2404.16130) — community summaries + map-reduce global queries; read for ideas, not adoption
- LightRAG (arXiv 2410.05779) + repo — dual-level retrieval; the repo is short, readable Python
- Graphiti (getzep/graphiti) — temporal knowledge graphs for memory; relevant at phase 7
- `instructor` docs — structured LLM outputs pattern
- *Designing Data-Intensive Applications* ch. 2–3 — derived data vs. source of truth; the mental model behind §1's "cache, not truth" principle
