# Design: Architecture Hardening & Retrieval Layer Foundations

**Date**: 2026-07-10
**Status**: Proposed — decision record
**Author**: Himanshu (with Claude)
**Scope**: Cross-cutting architecture (dependency inversion, layering, config) + the seams the
retrieval/eval/content work will be built on. **Not** a framework migration.

---

## 1. Purpose & how to read this

This is a **decision record**. It captures *why* we are changing the shape of the codebase and
locks in a target so future work (and future Claude sessions) inherit the plan, not just the code.

It **builds on**, and does not relitigate, two prior decisions:

- [2026-03-22 RAG Query Layer Framework Research](2026-03-22-rag-query-layer-framework-research.md) —
  decided: keep PostgreSQL + pgvector, LangChain-style retrieval, Streamlit playground, Langfuse.
- [2026-03-22 Query Layer Improvements](2026-03-22-query-layer-instagram-pipeline-design.md) —
  decided: FTS-based hybrid, RRF, reranker/query-expansion abstractions, content pipeline reuse.

Those answered *"what stack and what features."* They did **not** answer *"how do we keep the code
testable and the layers honest as this grows."* That gap is what this doc addresses.

Each decision below is written ADR-style: **Context → Decision → Rationale → Alternatives →
Consequences**, with before/after code from this repo. Decisions marked **OPEN** need your call;
the rest are recommendations I'm confident in.

**Reading order if short on time:** §3 (problems) → §6 (decisions D1, D2, D3, D6) → §8 (phased plan).

---

## 2. Context: where the code is now

This repo is mid-stage and **has good instincts that aren't applied consistently**. Credit first,
because the fixes below are "propagate what you already do well," not "start over."

**Already good (the model to copy):**

| Pattern | Where | Why it matters |
|---|---|---|
| Constructor injection | `GroundedAnswerService(llm_client=…, tracer=…)` — [retrieval/answering.py:62](../../retrieval/answering.py#L62) | Tests inject `FakeLLMClient` with zero mocking. This is the target for the whole codebase. |
| Optional injected dependency | `LangfuseTracer(client=…, settings=…)` — [observability/langfuse.py:103](../../observability/langfuse.py#L103) | Already a working *port*: no-ops when unconfigured, fakeable in tests. |
| Domain objects as dataclasses | `SearchResult`, `SearchResponse` — [retrieval/query.py:46](../../retrieval/query.py#L46) | Data separated from behavior. |
| Typed nested config | [config/settings.py](../../config/settings.py) | Correct foundation — we just bypass it too often (D4). |

**Already shipped since the query-layer design:** PostgreSQL FTS replacing in-memory BM25,
UUID-based RRF dedup + min-max score normalization, `EvalLLMClient`→`LLMClient` rename,
`_extract_header_paths` extracted to `retrieval/utils.py`.

**The forces pulling on the design now:**

- The retrieval layer is about to get **at least three consumers**: the RAG Playground UI, the
  **retrieval-eval loop** (the current `feature/rag-retrieval-eval` branch), and the planned
  **Instagram content pipeline** (reuses `RetrievalEngine` + `GroundedAnswerService`). Multiple
  consumers is the moment a clean boundary stops being optional.
- **Eval depends on chunk-UUID identity as ground truth** (per the Neon migration doc). Anything we
  build must preserve `chunks.uuid` ↔ `langchain_pg_embedding.uuid` linkage.
- **Solo maintainer**, so the goal is *leverage*: changes that make the next feature cheaper and the
  test loop faster — not ceremony.

---

## 3. Problems this doc addresses (ranked by leverage)

Each is anchored to real code. Ranked so the phased plan (§8) can pick the highest-leverage, lowest-
risk items first.

| # | Problem | Evidence | Cost today |
|---|---|---|---|
| **P1** | **DB engine built at import time** → nothing downstream is unit-testable without a DB env var | [db/database.py:19-54](../../db/database.py#L19-L54); 5 test files start with `os.environ.setdefault("DATABASE_URL", …)` | Slow, fragile tests; can't fake the DB |
| **P2** | **No repository seam** — SQLAlchemy leaks into retrieval & services 3 different ways | raw SQL in [retrieval/query.py:437-463](../../retrieval/query.py#L437-L463); `ChunkCRUD` in services; ORM in views | No cheap unit tests for retrieval enrichment |
| **P3** | **Layering violation** — `views/` import `session_scope`/CRUD directly | all 6 view files | UI changes can break data logic |
| **P4** | **Config bypassed** — `os.getenv` ×9 despite `Settings`; DB-URL rule duplicated ×4 | `retrieval/`, `services/`, `ingestion/`, `db/` | One change, four edit sites |
| **P5** | **Magic string already drifted** — collection name is `"documents"` in 3 files, `"meditation_chunks"` in 5 | [query.py:133](../../retrieval/query.py#L133) vs [collection_service.py:62](../../services/collection_service.py#L62) | Latent bug: search can query the wrong collection |
| **P6** | **Async in the wrong place** — only chunking has real concurrency; services/orchestrator async is sequential ceremony; the heavy I/O (embedding) is sync | real: [chunking.py:281-286](../../ingestion/chunking.py#L281-L286); ceremony: `asyncio.run()` ×6 | Complexity with no throughput; `asyncio.run()` footgun in Streamlit |
| **P7** | **Duplicated + deprecated vector-store setup** | `PGVector` built in both [query.py:158](../../retrieval/query.py#L158) and [embed.py:94](../../ingestion/embed.py#L94), both via deprecated `langchain_community` import | Drift; on a deprecated API while `langchain-postgres` is already a dep |
| **P8** | **Stale provider branching** post-Neon | `is_supabase` in [database.py:22](../../db/database.py#L22), [settings.py:60](../../config/settings.py#L60) | Dead/incorrect config path |

> **Reframing your two intuitions:** "too many folders" is really *unenforced boundaries between
> them* (P3) — the count is fine. "Dependency inversion for SQLAlchemy like Cosmic Python" is exactly
> right and is P1+P2 — the highest-leverage change in the doc.

---

## 4. Goals & non-goals

**Goals**
- G1 — Make persistence an **injected dependency**, so any layer is unit-testable without a database.
- G2 — Put a **repository seam** between the ORM and the rest of the code (Cosmic Python).
- G3 — **One source of truth** for config values (collection name, DB URL, provider).
- G4 — **Enforce layering**: `views → services → ports`; nobody skips to `db/`.
- G5 — **Decide the concurrency model** and put async only where it buys throughput.
- G6 — **Formalize retrieval ports** so the *already-planned* rerank / query-expansion / GraphRAG
  features plug in as adapters without touching callers.

**Non-goals (explicit YAGNI)**
- No framework migration — keep LangChain + pgvector + Streamlit + Langfuse (prior decision stands).
- No re-embedding and **no new chunk UUIDs** — eval ground truth must stay valid.
- Not building GraphRAG now — only leaving a port for it.
- Not rewriting working ingestion (chunking/parsing/embedding logic) — only its seams.
- No DI framework/container — a hand-wired composition root is enough at this size (see §11).

---

## 5. Guiding principles (with the reading list)

The named ideas behind every decision. Full references in §12.

1. **The Dependency Rule** (Clean Architecture) — source-code dependencies point *inward*, toward the
   domain. Infrastructure (DB, vector store, LLM) depends on the domain, never the reverse.
2. **Ports & Adapters / Hexagonal** — the core declares *interfaces (ports)*; databases and models
   are *adapters*. You already do this with `LangfuseTracer` and the planned `BaseReranker`.
3. **Repository & Unit of Work** (Cosmic Python ch. 2, 6) — hide the ORM behind a collection-like
   interface; the UoW owns the transaction boundary. This is the direct answer to your ask.
4. **Dependency Inversion (SOLID-D)** — depend on abstractions, inject concretions. `answering.py`
   already does; `db/` doesn't.
5. **Single Responsibility (SOLID-S)** — `query.py` currently mixes 5 concerns; split them.
6. **Config once, at the edge** (12-Factor, Factor III) — read env into `Settings` in one place.
7. **Composition Root** — construct and wire dependencies in exactly one place.
8. **Async at the boundary of I/O, sync at the boundary of the UI.**

---

## 6. Target architecture

**The Dependency Rule, applied.** Today some arrows point the wrong way (retrieval → raw SQL,
views → db). Target:

```
        ┌──────────────────────────────────────────────────────────────┐
        │  ADAPTERS (infrastructure — swappable, the only place I/O lives)│
        │  SqlAlchemyChunkRepository  PgVectorRetriever  FtsRetriever     │
        │  VoyageEmbedder   BGEReranker   LiteLLMClient   LangfuseTracer  │
        └───────────────▲───────────────────────────▲──────────────────┘
                        │ implements                 │ implements
        ┌───────────────┴───────────────────────────┴──────────────────┐
        │  PORTS  (interfaces / Protocols, in core/) — no I/O imports    │
        │  ChunkRepository  Retriever  Reranker  Embedder  LLMClient     │
        └───────────────▲───────────────────────────────────────────────┘
                        │ depends on abstractions only
        ┌───────────────┴───────────────────────────────────────────────┐
        │  APPLICATION / use-cases (services/)                           │
        │  SearchDocuments   AnswerQuestion   IngestDocument   Reprocess │
        └───────────────▲───────────────────────────────────────────────┘
                        │ called by (thin) consumers
   ┌────────────────────┼───────────────────────┬─────────────────────────┐
   │ views/ (Streamlit) │ eval loop (notebooks) │ content/ (Instagram)    │  future: API
   └────────────────────┴───────────────────────┴─────────────────────────┘

   Wiring happens once, in a composition root (a small factory module).
```

**Why this shape is right for *this* repo specifically:** the three consumers (playground, eval,
content pipeline) all need the *same* `SearchDocuments` / `AnswerQuestion` behavior. If that behavior
lives behind ports, eval can run it with a `FakeRetriever` for deterministic tests, the content
pipeline can run it with `rerank=True`, and the UI can stream it — with **one** implementation.

**Target module layout** (mostly *moves*, few new files):

```
core/
  ports.py          # NEW  Protocols: ChunkRepository, Retriever, Reranker, Embedder, LLMClient
  models.py         # domain dataclasses (SearchResult, SearchResponse already exist → move here)
  exceptions.py     # exists
db/
  database.py       # CHANGED  Database class (no module-level engine)
  repositories.py   # NEW  SqlAlchemyChunkRepository, SqlAlchemyDocumentRepository
  schema.py         # exists (ORM only — never imported above the adapter layer)
  crud.py           # keep as low-level helpers used *by* repositories, or fold in over time
retrieval/
  retriever.py      # RENAME of query.py's engine → PgVectorRetriever (implements Retriever)
  fusion.py         # NEW  RRF math extracted out of query.py
  rerank.py         # NEW  BaseReranker + BGEReranker (planned, now behind a port)
  answering.py      # exists (already correct DI)
  llm_client.py     # exists
services/
  search.py         # NEW  SearchDocuments, AnswerQuestion use-cases
  ingestion_service.py / collection_service.py  # slimmed: depend on repositories, not session_scope
composition.py      # NEW  build_* factories — the one place things are wired
config/settings.py  # + VectorSettings (collection_name), drop is_supabase → provider enum
```

---

## 7. Design decisions

### D1 — Make the database an injected dependency (fixes P1, P8) · **Recommended**

**Context.** [db/database.py](../../db/database.py) builds the engine and `SessionLocal` at *import
time* (lines 19–54), and branches on `is_supabase` — now stale after the Neon move. Because import
triggers a connection, **five** test files must fake an env var just to import unrelated modules:

```python
# tests/retrieval/test_answering.py:4  — a unit test of answer synthesis, coupled to the DB
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
```

**Decision.** Replace module-level globals with a `Database` object constructed from `Settings`. No
connection happens on import. Provider differences (Neon/Supabase/local) become config, not code.

**Before → After.**

```python
# BEFORE — db/database.py (module level: connects on import, provider hard-coded)
settings = get_settings()
if settings.database.is_supabase:
    engine = create_engine(settings.database.url, pool_size=…, connect_args={"sslmode": "require"})
else:
    engine = create_engine(settings.database.url, pool_size=5)
SessionLocal = sessionmaker(bind=engine)

def session_scope(): ...   # uses the global SessionLocal
```

```python
# AFTER — db/database.py (a constructed object; nothing runs on import)
class Database:
    """Owns the engine + session factory. Built once, at the composition root."""
    def __init__(self, settings: DatabaseSettings):
        self._session_factory = sessionmaker(bind=self._build_engine(settings), autoflush=False)

    @staticmethod
    def _build_engine(s: DatabaseSettings):
        kwargs = dict(echo=s.echo, pool_pre_ping=True, pool_recycle=s.pool_recycle)
        if s.ssl_required:                       # config, not `is_supabase`
            kwargs["connect_args"] = {"sslmode": "require"}
        return create_engine(s.url, pool_size=s.pool_size, max_overflow=s.max_overflow, **kwargs)

    @contextmanager
    def session_scope(self):
        session = self._session_factory()
        try:
            yield session; session.commit()
        except Exception:
            session.rollback(); raise
        finally:
            session.close()
```

```python
# AFTER — tests/conftest.py gains a real fixture; the env-var hack disappears from 5 files
@pytest.fixture
def db() -> Database:
    return Database(DatabaseSettings(url="sqlite+pysqlite:///:memory:"))  # or a throwaway pg
```

**Rationale.** This is the root-cause fix for testability (G1) and removes the stale provider branch
(P8) in the same move.
**Alternatives.** (a) Keep the global, add a `reset_engine()` for tests — still couples import to
config, rejected. (b) A DI container (`dependency-injector`) — overkill at this size (§11).
**Consequences.** A `Database` instance must be threaded through the composition root. `session_scope`
becomes a method; call sites that used the module function change to use the injected instance (small,
mechanical). Migration is Phase P1.

---

### D2 — Repository + Unit of Work over SQLAlchemy (fixes P2) · **Recommended** *(your explicit ask)*

**Context.** "How do I fetch chunks" is answered three ways: raw parameterized SQL inside the
retrieval engine ([query.py:445-461](../../retrieval/query.py#L445-L461)), `ChunkCRUD(session)` in
services, and ORM queries in views. None is substitutable, so retrieval enrichment has no unit test.

**Decision.** Define repository **ports** in `core/`, implement SQLAlchemy **adapters** in `db/`, and
have callers depend on the port. The existing `session_scope` becomes the Unit of Work boundary.

**Before → After.**

```python
# BEFORE — retrieval/query.py: retrieval reaches straight into SQL
with session_scope() as session:
    placeholders = ", ".join([f":uuid_{i}" for i in range(len(uuids))])
    rows = session.execute(text(f"SELECT c.uuid, c.chunk_index, … WHERE c.uuid IN ({placeholders})"),
                           params).fetchall()
```

```python
# AFTER — core/ports.py (abstraction; NO sqlalchemy import here)
class ChunkRepository(Protocol):
    def enrichment_for(self, uuids: Sequence[str]) -> dict[str, ChunkEnrichment]: ...

# db/repositories.py (the adapter; the only place ORM/SQL lives)
class SqlAlchemyChunkRepository:
    def __init__(self, session: Session): self._s = session
    def enrichment_for(self, uuids):
        rows = (self._s.query(Chunk.uuid, Chunk.chunk_index, Chunk.document_id, Document.title)
                       .join(Document).filter(Chunk.uuid.in_(list(uuids))).all())
        return {r.uuid: ChunkEnrichment(r.chunk_index, r.document_id, r.title) for r in rows}
```

The retriever takes a `ChunkRepository` in its constructor (exactly like it already takes `tracer`).
Tests pass a dict-backed `FakeChunkRepository` — **no DB, no SQL, instant**.

**Rationale.** This is the Cosmic Python pattern you named; it turns P2 from "untestable" into the
same clean story `answering.py` already enjoys. Repositories also centralize the UUID-identity logic
the eval loop depends on.
**Alternatives.** (a) Keep CRUD, just inject the session — better than today but still leaks the ORM
into business code; repository is the fuller fix. (b) Full generic UoW abstraction — adopt only if a
second DB backend appears; a session-scoped UoW is enough now.
**Consequences.** New `db/repositories.py`; `CollectionService` and the retriever take repositories
instead of opening sessions themselves. Phase P2.

---

### D3 — Retrieval as ports & adapters (fixes P2, P7; enables G6) · **Recommended**

**Context.** You already invented the right shape once — the approved design has `BaseReranker` with
`BGEReranker`/`CohereReranker`. That's a port with adapters. But `RetrievalEngine` builds its own
`PGVector` ([query.py:158](../../retrieval/query.py#L158)) separately from `VectorStoreManager`
([embed.py:94](../../ingestion/embed.py#L94)), both via the **deprecated** `langchain_community`
import, and `query.py` mixes strategy dispatch, four algorithms, RRF math, SQL enrichment, and
tracing (SRP, P7 + P1's cousin).

**Decision.** Generalize the reranker instinct to the whole retrieval layer:

```python
# core/ports.py
class Retriever(Protocol):
    def retrieve(self, query: str, k: int, **opts) -> list[SearchResult]: ...
class Reranker(Protocol):
    def rerank(self, query: str, results: list[SearchResult], k: int) -> list[SearchResult]: ...
class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

- `PgVectorRetriever` and `FtsRetriever` become adapters implementing `Retriever`.
- RRF moves to `retrieval/fusion.py` (pure function, trivially testable).
- Enrichment moves behind `ChunkRepository` (D2).
- The planned `rerank` / `expand_query` / `document_ids` params (approved, **not yet built**) become
  either adapter options or a `HybridRetriever` composed of others — added without changing callers.
- Consolidate on `langchain_postgres.PGVector` (already a dependency) in one adapter; delete the
  duplicate construction.

**Rationale.** `query.py` drops from 463 lines mixing five concerns to a thin composition of testable
pieces. GraphRAG later is "a new `Retriever` adapter," not a rewrite (matches your YAGNI stance).
**Alternatives.** Leave `RetrievalEngine` monolithic and add flags — it's already the file most likely
to grow unmaintainable with rerank+expand+graph piled on.
**Consequences.** Rename/split of `query.py`; keep `SearchResult`/`SearchResponse` as the stable
domain types (they're good). Phase P3.

---

### D4 — Single source of truth for config (fixes P4, P5) · **Recommended · do first**

**Context.** The vector collection name exists as a literal in 8 files with **two different values**
(P5) — a latent bug where retrieval can read a different collection than ingestion writes. Separately,
`db_url = … or os.getenv("DB_URL") or os.getenv("DATABASE_URL")` is copy-pasted in 4 places (P4),
even though [settings.py:45](../../config/settings.py#L45) already resolves it.

**Decision.** Add a `VectorSettings` section; make every default read from `Settings`.

```python
# config/settings.py
class VectorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VECTOR_", extra="ignore")
    collection_name: str = Field(default="meditation_chunks")
# Settings: vector: VectorSettings = Field(default_factory=VectorSettings)
```

Then `collection_name="documents"` and `= "meditation_chunks"` literals both become
`get_settings().vector.collection_name`, and every `os.getenv("DB_URL") …` becomes
`get_settings().database.url`.

**Rationale.** 20-minute change that closes a real correctness gap and removes 4 duplicated rules.
**Consequences.** Pick the canonical collection name (recommend `meditation_chunks`, the more
specific) and confirm existing data lives there before flipping the `"documents"` defaults. Phase P0.

---

### D5 — Enforce layering: `views → services → ports` (fixes P3) · **Recommended**

**Context.** All six view files import `session_scope`/CRUD directly, so presentation does data access.

**Decision.** Views may import `services/` (and domain models) but **never** `db/`. Data crosses the
boundary as plain DTOs/domain dataclasses.

```python
# BEFORE — views/browse.py
from db.database import session_scope
from db.crud import DocumentCRUD
with session_scope() as s: docs = DocumentCRUD(s).get_all_documents()   # ORM objects in the UI

# AFTER — views/browse.py
from services.documents import list_documents
docs = list_documents(status="completed")    # returns plain DocumentDTO; no DB import in the view
```

Encode the rule as an **import-linter** contract in CI so it can't silently regress.
**Alternatives.** Convention-only (no linter) — regresses; the contract is cheap.
**Consequences.** Some read-only views need thin service functions. Phase P4.

---

### D6 — Concurrency model & the Streamlit boundary (fixes P6) · **the async question** · one part **OPEN**

**Context — the myth, stated plainly.** *Async does not make Streamlit "behave better."* Streamlit
re-runs the whole script **synchronously**, top-to-bottom, once per interaction, one `ScriptRunner`
thread per session. It is not an async framework; your page code does not live inside a persistent
event loop. A button-triggered action *should* block until it has a result to render.

**What the code actually does** (measured, not assumed):
- **Real concurrency: one place only** — semantic chunking runs blocking work in a `ThreadPoolExecutor`
  and awaits it with `asyncio.gather` ([chunking.py:281-286](../../ingestion/chunking.py#L281-L286)).
  Legitimate; keep it.
- **Ceremony async: everywhere else** — `collection_service`, `ingestion_service`, and the orchestrator
  stages are `async def` that `await` sequentially. **Zero** concurrency; pure overhead. Exposed to the
  UI through `asyncio.run()` wrappers (×6).
- **The actual heavy I/O is synchronous** — Voyage embedding is a plain batch loop in
  [embed.py:161-202](../../ingestion/embed.py#L161-L202). The one thing that would benefit from
  concurrency isn't async at all.

So async is currently in the *wrong place*: ceremony where there's no concurrency, sync where the I/O is.

**Decisions.**

1. **Keep the Streamlit boundary synchronous.** The `_sync` wrapper instinct is correct. But replace
   fragile `asyncio.run()` (raises `RuntimeError: asyncio.run() cannot be called from a running event
   loop` when a loop already exists in the thread — increasingly common with torch/grpc/newer
   Streamlit) with **one** robust runner:

   ```python
   # utils/async_bridge.py
   def run_sync(coro):
       try:
           running = asyncio.get_running_loop()
       except RuntimeError:
           running = None
       if running:                          # already inside a loop → offload to a worker thread
           with ThreadPoolExecutor(1) as pool:
               return pool.submit(asyncio.run, coro).result()
       return asyncio.run(coro)
   ```

2. **OPEN — pick one for the ceremony-async services:**

   | Option | What | When it's right |
   |---|---|---|
   | **6a (recommended): make them sync** | Drop `async`/`await` from `collection_service`, `ingestion_service`, orchestrator stages that don't concurrently do I/O | You value simplicity/debuggability; concurrency isn't needed there (it isn't today) |
   | 6b: make the async *real* | Add `asyncio.gather` where it pays — concurrent embedding batches, concurrent multi-doc parsing | You want ingestion throughput and will maintain async end-to-end |

   My recommendation is **6a now, 6b only for embedding if/when ingestion speed hurts** — and even then
   a `ThreadPoolExecutor` (like chunking already uses) is simpler than making the whole stack async.

3. **The real UX wins people reach for async to get — get them directly:**
   - `st.status()` / `st.progress()` for long-op feedback (a blocking op with a spinner is fine).
   - **`st.write_stream()` for streaming RAG answers** — `LLMClient.complete()` is non-streaming today;
     add a `stream()` generator (litellm `completion(stream=True)` yields `choices[0].delta.content`).
     This is a **sync generator** — perfect for Streamlit, no asyncio. High-value for the playground.
   - For genuinely long ingestion: a **background worker + status polling** (you already have a
     "Processing Queue" view concept), not async — Streamlit is not a job runner.

**Consequences.** Removes a whole class of `asyncio.run()` bugs; concentrates concurrency where it
earns its keep; unlocks streaming answers. Phase P5.

---

### D7 — Naming reconciliation · **OPEN (small)**

The 2026-03-22 research doc proposed `query_service.py`, `QueryRequest`, `RetrievedChunk`,
`QueryResponse`. The code that shipped uses `RetrievalEngine`, `SearchResult`, `SearchResponse`,
`GroundedAnswerService`. **Recommendation:** treat the *implemented* names as canonical (they won,
they're fine) and mark the research-doc names superseded, so we stop carrying two vocabularies. Your
call if you prefer the `Query*` naming instead.

---

## 8. Phased migration plan

Ordered low-risk / high-leverage first. Each phase is independently shippable and leaves the app
working. "Done when" is the acceptance check.

| Phase | Scope | Decisions | Done when |
|---|---|---|---|
| **P0** | `VectorSettings`; replace `collection_name` + `db_url` literals with `Settings` | D4 | One collection name in the code; grep for `os.getenv("DB_URL")` in app code is empty; app still searches & ingests |
| **P1** | `Database` object; delete module-level engine + `is_supabase`; `conftest` `db` fixture | D1, P8 | The `os.environ.setdefault("DATABASE_URL")` hack removed from all 5 test files; tests import with no DB |
| **P2** | `core/ports.py` (repos) + `db/repositories.py`; retriever & `CollectionService` take repositories | D2 | `FakeChunkRepository` unit test covers retrieval enrichment; no raw SQL in `retrieval/` |
| **P3** | Split `query.py` → `retriever.py` + `fusion.py`; consolidate on `langchain_postgres`; add `Reranker`/`Embedder` ports; wire pending rerank/expand/`document_ids` behind them | D3 | `query.py` concerns separated; `fusion.py` has pure-function tests; rerank toggle works via a `Reranker` adapter |
| **P4** | `services/search.py` use-cases; move view DB access behind services; import-linter contract | D5 | No `views/*` imports `db`; CI contract green |
| **P5** | `run_sync` bridge; apply D6-open choice; add `LLMClient.stream()` + `st.write_stream` in playground | D6 | No `asyncio.run()` in views; RAG answer streams token-by-token |
| **P6** *(future)* | GraphRAG as a `Retriever` adapter; content pipeline on the stable use-cases | D3 | GraphRAG added with zero caller changes |

**Suggested first PR:** P0 alone — 20 minutes, closes the P5 collection-name bug, no risk.

---

## 9. Testing strategy

The seams above exist *to make this cheap*:

- **Unit** — pure logic with fakes, no infra. Model already exists: `FakeLLMClient` /
  `FakeLangfuseClient` in [tests/retrieval/test_answering.py](../../tests/retrieval/test_answering.py).
  After D1/D2, add `FakeChunkRepository` and `FakeRetriever`; `fusion.py` gets direct RRF tests.
- **Integration** — real `Database` against a throwaway Postgres (or SQLite where dialect allows),
  constructed via the fixture, not env vars.
- **Eval as a test surface** — the retrieval-eval loop becomes a first-class integration harness:
  because retrieval is behind a port, the eval notebook/script can run the *same* `SearchDocuments`
  the UI uses, over the UUID-ground-truth dataset, and compare strategies deterministically.
- **Guardrail** — the import-linter contract (D5) is a test that layering hasn't regressed.

---

## 10. Risks & open questions

- **R1 — scope creep vs. eval momentum.** You're mid-eval on `feature/rag-retrieval-eval`. Do P0+P1
  (fast, unblock tests) and D6 streaming; defer P2–P4 until after the current eval milestone if it
  competes for attention.
- **R2 — D6-open (6a vs 6b).** Needs your call; recommendation is 6a. Cheap to reverse.
- **R3 — D7 naming.** Trivial but pick one to avoid two vocabularies.
- **R4 — canonical collection name & data location.** Confirm where current embeddings actually live
  before flipping D4 defaults (a quick `SELECT name FROM langchain_pg_collection`).
- **R5 — SQLite-in-tests dialect gaps** (JSONB, ARRAY, pgvector). May need a throwaway Postgres for
  integration tests even after D1; unit tests via fakes are unaffected.

---

## 11. Why *not* a DI framework (recorded, so we don't relitigate)

`dependency-injector` / heavy IoC containers solve a problem this codebase doesn't have yet
(large graphs, many runtime-selected implementations). A **hand-wired composition root** — one
`composition.py` with `build_database()`, `build_retriever()`, `build_search_service()` factories —
gives all the testability benefits with zero magic and no new dependency. Revisit only if wiring
becomes genuinely unwieldy.

---

## 12. References & reading order

For you, shortest path first (~2 hrs covers 80% of this doc):

1. **Cosmic Python** — *Architecture Patterns with Python*, Percival & Gregory. **Free**:
   [cosmicpython.com](https://www.cosmicpython.com/book/preface.html). Read **ch. 2 (Repository)** →
   **ch. 6 (Unit of Work)** → ch. 4 (Service Layer). This is D1/D2/D5 directly.
2. **12-Factor App, Factor III — Config**: [12factor.net/config](https://12factor.net/config) (D4).
3. **The Clean Architecture** (the Dependency Rule):
   [blog](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html) (§6).
4. **Ports & Adapters** — Alistair Cockburn's hexagonal architecture article (§6).
5. **Refactoring** (Fowler, 2e) — names for the mechanical moves; smell list at
   [refactoring.guru](https://refactoring.guru/refactoring/smells) (P7 split).
6. **pytest fixtures** — [docs](https://docs.pytest.org/en/stable/how-to/fixtures.html) (§9, the
   `db` fixture replacing env hacks).
7. **Streamlit execution model** — [docs](https://docs.streamlit.io/develop/concepts/architecture/run-your-app)
   and `st.write_stream` for D6.

---

## Appendix A — glossary

- **Port** — an interface (Python `Protocol`/ABC) the core depends on; e.g. `Retriever`.
- **Adapter** — a concrete implementation of a port that talks to real infrastructure; e.g.
  `PgVectorRetriever`.
- **Repository** — a collection-like port for aggregate persistence, hiding the ORM.
- **Unit of Work** — the transaction boundary that commits/rolls back a set of repository operations
  (here, `Database.session_scope`).
- **Composition root** — the single place that constructs and wires concrete dependencies.
