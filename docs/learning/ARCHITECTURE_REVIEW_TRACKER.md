# Architecture & Python Patterns Review — Progress Tracker

## Purpose

Running index for a folder-by-folder architecture + Python-patterns review of this codebase, done collaboratively across multiple sessions with Claude. Companion doc: [LEARNINGS_BLOG.md](LEARNINGS_BLOG.md) — narrative writeup of what's actually worth remembering, drafted candidly and code-specific for now, to be genericized into a publishable post later.

## How to resume a session

1. Check "Queue" below for the next unchecked folder.
2. Skim the most recent entry in "Per-Folder Notes" for continuity/style.
3. Read the folder's source, discuss, fill in a new entry here, append to the blog doc.
4. Check the box, log the session in "Session Log".

## Review lens (recap so this stays consistent across sessions)

For each folder:

- **What it does** — role in the pipeline/system
- **Abstraction level** — is it at the right altitude? Leaky abstractions? Right things hidden vs. exposed?
- **Best-practice read** — coupling/cohesion, error handling, testability, SOLID-ish concerns
- **Notable Python patterns** — anything beyond basics: descriptors, protocols, dataclasses vs. Pydantic, context managers, decorators, dependency injection, ABCs, generics, DAG/strategy/factory patterns, async patterns, etc.
- **Open questions / follow-ups**

## Dependency order (evidence-based)

Derived by grepping actual cross-package imports (`grep -rlE "^(from|import) <pkg>"`), not assumed from folder names.

- **Tier 0** (no internal deps — true foundations): `config`, `core`
- **Tier 1** (depend on Tier 0): `db`, `observability` (→ `config` only)
- **Tier 2**: `ingestion` (→ `core`)
- **Tier 3**: `retrieval` (→ `db`, `observability`)
- **Tier 4**: `services` (→ `core`, `db`, `ingestion`)
- **Tier 5**: `views` (→ `core`, `db`, `retrieval`, `services`)
- **Entrypoint**: `app.py`, root `config.py`

Cross-cutting, reviewed after the main stack: `tests`, `scripts`, `alembic`, `docker`.
Light/optional pass: `experiments`, `reports`, `data` (and `Books/`, which is content, not code — skip unless something interesting turns up).

## Queue

- [x] `config/`
- [x] `core/`
- [x] `db/`
- [x] `observability/`
- [x] `ingestion/`
- [x] `retrieval/`
- [ ] `services/`
- [ ] `views/`
- [ ] `app.py` / root `config.py` (entrypoint)
- [ ] `tests/`
- [ ] `scripts/`
- [ ] `alembic/`
- [ ] `docker/` (light)
- [ ] `experiments/`, `reports/`, `data/` (light)

## Session Log

### Session 1 — 2026-07-11

- Scoped the exercise with Himanshu: all folders, dependency order; blog doc is candid/code-specific now, will get a genericizing pass before publishing.
- Mapped the real cross-folder dependency graph via grep instead of guessing from CLAUDE.md (which is stale — repo has grown to include `retrieval/`, `services/`, `observability/`, `views/`, `scripts/`, `alembic/`, `docker/`, `experiments/`, `tests/` beyond what's documented).
- Set up this tracker + companion blog doc.
- Completed `config/` (see notes below).
- Next: `core/`.

### Session 2 — 2026-07-13

- Completed `core/` and `db/` (notes below).
- Read `ingestion/stages.py` + `ingestion/orchestrator.py` ahead of schedule to answer three strategic questions from Himanshu (free hosting, ingestion-as-API, enrichment extensibility). Answers recorded in "Strategic Questions" section below.
- Started a "Refactor Backlog" section (bottom of this doc) — mode going forward: log findings here, apply refactors only when Himanshu picks them.
- Bonus finding while checking the service layer: `services/ingestion_service.py:29` reads `os.getenv("DB_URL")` directly, bypassing the `config/` boundary. Filed in backlog; full `services/` review still pending.
- Next: `observability/`, then finish `ingestion/` (chunking.py, parsing.py, embed.py, suttacentral.py).

### Session 3 — 2026-07-13

- Deep-dive teaching session on the two headline findings (PipelineContext immutability, CRUD transaction ownership), then **applied backlog #1 and #3 via TDD**:
  - RED: 15 new contract tests written and watched fail (`tests/test_crud_transaction_ownership.py`, `tests/test_pipeline_context_immutability.py`).
  - GREEN: CRUD `commit()+refresh()` → `flush()`; `PipelineContext` frozen; `EmbeddingStage` copies chunks; removed 2 redundant interior commits.
  - Verified: 112/112 tests pass, ruff clean, mypy unchanged (61 pre-existing errors at HEAD and after — legacy `Column[]` typing, fixed by backlog #8).
- Blog entry 4 added: "Who owns state change?" — detailed case study of both fixes.
- Committed on branch `refactor/state-ownership`; rebased onto main (PR #4 was squash-merged, so the branch was replayed onto `origin/main` to keep the diff clean); **PR #5 opened**: https://github.com/HimanshuBhardwaj2398/meditation-assistant/pull/5
- Completed `observability/` and the rest of `ingestion/` (notes below). Three verified findings: CHUNKING_* env settings never reach the chunker; two distinct `EmbeddingError` classes make a `catch` branch dead; deprecated `langchain_community` PGVector used while `langchain-postgres` is installed but unused. Backlog #10–#16 added.
- Next: `retrieval/`.

### Session 4 — 2026-07-13 (later)

- **Backlog batch applied via TDD** on fresh branch `chore/backlog-cleanup` (main pulled first; PR #5 had been merged): items #4, #5, #6, #7/#11, #9, #10, #12, #13, #16. 16 new tests (RED verified first), 128 total passing, ruff clean, mypy 71 vs 72 at baseline.
- Deferred with reasons: #2 (needs live DB), #8 (dedicated PR), #14 (data-compat plan), #15 (behavioral decision) — see backlog table.
- Learned along the way: pydantic-settings resolves `AliasChoices` in alias order *across sources* — a `DB_URL` in the dotenv file outranks a `DATABASE_URL` in the real environment. Made the config-boundary tests hermetic (chdir to tmp) rather than dependent on the developer's `.env`.
- Next: `retrieval/`.

### Session 5 — 2026-07-14

- PR #6 (backlog batch) went green after one CI round-trip: local verification ran `ruff check` but CI also runs `ruff format --check` — two files needed reformatting. Lesson: local verification must mirror CI's exact commands.
- Completed `retrieval/` (notes below). New backlog items #17–#21.
- Next: `services/`.

### Session 6 — 2026-07-15

- **Backlog round 2 applied via TDD** on branch `chore/backlog-round-2`: #2, #15 (chars decision), #17 (+ narrow-settings policy + TID251), #18, #19, #20 (doc-level), #21. 136 tests passing (+8), ruff/format clean, mypy 74 vs 75 baseline.
- **Migration applied to live Neon** (`b7c9d1e3f5a7`): dupe check first (0 dupes on 5 documents), `alembic stamp` baseline (DB had no alembic_version — schema originally from `init_db()`), then upgrade. Verified read-only: both indexes present, tsv 24/24, FTS query returns ranked hits.
- **Two discoveries**: (a) resolving one settings key via composed `get_settings()` forces validation of *all* groups — hence the narrow-groups policy; the old behavior also hid a test-order dependency (tests passed only because unrelated modules set `DATABASE_URL` at import). (b) `.env`'s `DB_URL` points at the dead Supabase instance — filed as #23 for Himanshu.
- Next: `services/` review.

## Strategic Questions (asked session 2, answered with code evidence)

### 1. Can we host document ingestion somewhere free?

Yes — the stack decomposes cleanly because the heavy pieces are already external APIs:

- **Database**: already on Neon free tier (post-migration, see docs/plans/2026-07-08).
- **Embeddings**: Voyage API (free tier); **PDF parsing**: LlamaParse API (free tier). Neither costs local compute.
- **The one heavy local piece**: semantic chunking loads `BAAI/bge-small-en-v1.5` via `HuggingFaceEmbeddings` (`ingestion/chunking.py:119`) — torch + model ≈ 500MB–1GB RAM. Verified by grep this is *only* in the ingestion path; `retrieval/`, `views/`, `services/` never import sentence-transformers.
- **Consequence**: a query-only Streamlit UI fits Streamlit Community Cloud's ~1GB free tier; but the UI's ingest tab runs the orchestrator in-process, which pulls in the chunking model and likely blows 1GB.

**Recommended free topology**: (a) batch ingestion via GitHub Actions `workflow_dispatch`/cron — free, 7GB-RAM runners, secrets management built in, and the CLI scripts already exist; (b) UI on Streamlit Community Cloud with ingest tab hidden/disabled, or the whole app on Hugging Face Spaces (16GB RAM free) if the ingest tab must stay. Neon remains the shared state between them.

### 2. Should ingestion flows become APIs?

**Not yet — but the code is already shaped for it, which is the important part.** Reasons to wait: single operator, batch workload, and jobs run minutes (LlamaParse + embedding), which doesn't fit HTTP request/response — a real API needs 202-Accepted + job polling + a worker, i.e., three new pieces of infrastructure for zero current clients.

The evidence that the architecture is *ready* when the time comes: `DocumentStatus` is already an async-job state machine (PENDING→…→COMPLETED/FAILED, persisted per stage transition via `_persist_stage_status` in orchestrator.py); processing is resumable/idempotent (`ReprocessMode`, `should_skip`); and `services/ingestion_service.py` is the seam — the API would be a *third client* of the same service functions (after CLI scripts and Streamlit views). The future shape: `POST /documents` → create doc, return 202 + id, run pipeline in background → `GET /documents/{id}` reads status. Nothing in the pipeline itself would change. That's the payoff of having a service layer.

### 3. Is the code simple enough to add enrichment later (summaries, generated tags per chunk/document)?

**Yes — this is the architecture's strongest suit — with one caveat to fix first.**

Ready today, no migration needed:
- **Pipeline**: `PipelineStage` ABC + DAG orchestrator means an `EnrichmentStage` with `required_stages = ["parsing"]` (doc-level summary) or `["database_persistence"]` (chunk tags) just gets topologically sorted in. This is exactly the extension point the design bought.
- **Storage**: `Document.tags` (ARRAY), `doc_metadata` (JSONB), `chunk_metadata` (JSONB) already exist, and CRUD already has merge-mode updates (`update_doc_metadata`, `update_chunk_metadata` with `merge=True`). Summaries/tags can land in JSONB immediately; promote to real columns via Alembic only once query patterns demand indexing.
- **No re-embedding required**: enrichment lives beside vectors, not inside them. The TOC-building in `DatabasePersistenceStage._build_table_of_contents` is precedent — derived metadata computed post-hoc and merged into `doc_metadata`.
- There's already a plan doc: docs/ENRICHMENT_LAYER_PLAN.md.

The caveat: **CRUD methods self-commit** (see db/ notes below). Multi-step enrichment (update N chunks + doc metadata atomically) can't be transactional until commit ownership moves to the caller. Fix that first — it's backlog item #1.

One honest wrinkle: chunk metadata is *duplicated* into the vector store (`langchain_pg_embedding.cmetadata`) at embed time. Tags added after embedding exist only in the `chunks` table — retrieval-time filtering on new tags needs either a join via `chunks.uuid` or a metadata update in the vector store. Not a blocker, but a sync question every enrichment design must answer.

## Per-Folder Notes

Filled in as each folder is completed, in review order. Use the Queue above to jump around; use your editor's search for a specific folder name.

---

### `config/` — Tier 0 foundation

**Files**: `__init__.py` (3 lines, re-export facade) · `settings.py` (302 lines) · `logging_config.py` (38 lines)

**What it does**: Centralizes all environment-derived configuration behind Pydantic Settings models, and configures the root logger. Verified via grep that nothing else in the repo calls `os.getenv`/`os.environ` for config — this module is the sole boundary between "the environment" and "typed settings."

**Abstraction level**: Right altitude. Exposes exactly two things to application code: `get_settings()` and the `Settings` type. Nobody outside `config/`, `alembic/env.py` (an entrypoint), and `tests/` constructs `Settings()` directly. Nested settings groups (`DatabaseSettings`, `EmbeddingSettings`, `LangfuseSettings`, etc.) are independently importable too — `observability/` imports `LangfuseSettings` straight from `config.settings` rather than going through the composed root. That's not a layering violation, it's the module offering two valid doors in (whole-app config vs. single-concern config) and letting callers pick the narrower one when that's all they need.

**Best-practice notes**:
1. **Dead code** — `_get_db_url`, `_get_voyage_api_key`, `_get_llamaparse_api`, `_get_hf_token` (settings.py:288-301) have zero call sites anywhere in the repo (verified by grep). Leftover from a pre-pydantic-settings migration. Safe to delete.
2. **Vestigial validator** — `ChunkingSettings.validate_max_size` (settings.py:159-165) is a no-op; its own docstring admits the real check happens elsewhere. Either delete it or move the real check here (see next point).
3. **Invariant enforced one level too high** — `max_size > min_size` is a property of `ChunkingSettings` alone, but it's checked in the *parent's* `Settings.model_post_init` (settings.py:268-274). Anyone who instantiates `ChunkingSettings(max_size=1, min_size=100)` directly gets zero validation. `model_post_init` works at any nesting level — the check belongs on `ChunkingSettings` itself.
4. **Style inconsistency** — `settings.py` uses `Optional[str]` throughout; `logging_config.py`, three files away, uses `str | int | None`. Both work on the project's Python floor (3.11+), but ruff's configured rule set (`select = ["E", "F", "I", "N", "W"]` in `pyproject.toml`) doesn't include `UP` (pyupgrade), which is what would catch `Optional[X]` vs `X | None` drift automatically.
5. **Env-var aliasing done the long way** — four `field_validator(mode="before")` methods exist purely so one field can be satisfied by two env var names (`DB_URL` or `DATABASE_URL`, etc). Pydantic v2 has a first-class feature for exactly this: `Field(validation_alias=AliasChoices("DB_URL", "DATABASE_URL"))`. Same result, no custom method, no manual `os.getenv` call hidden in a validator body.

**Notable Python patterns**:
- **Cached-factory singleton** — `@lru_cache() def get_settings() -> Settings` instead of a module-level `settings = Settings()`. Lazy (confirmed `__init__.py` only imports the function, never calls it, so nothing loads/validates at import time), and swappable in tests via `get_settings.cache_clear()`. This exact shape is also the textbook pattern behind FastAPI's `Depends(get_settings)`, if this project ever grows an API layer. Tradeoff: it's a process-lifetime cache, so `os.environ` changes after the first call are invisible until `cache_clear()`. Not an active bug — `tests/test_settings.py` sidesteps it entirely by constructing `Settings()` / `DatabaseSettings()` directly instead of calling `get_settings()`, which is the convention worth keeping for future settings tests.
- **Config objects carrying behavior, not just data** — `DatabaseSettings.is_remote` and `LangfuseSettings.is_configured` are `@property` methods that answer a question once instead of every call site reimplementing the same `if`. `is_remote`'s docstring states the non-obvious *why* (Neon scale-to-zero drops idle pooled connections) rather than the *what* — a good model for comment style generally.
- **`model_post_init` for cross-field validation** — the Pydantic v2 hook that sees the fully-constructed model, including nested sub-models, after defaults apply. The right tool when a rule spans more than one field and a plain `field_validator` can't see both sides.
- **`logging.basicConfig(..., force=True)`** — obscure but load-bearing. By default, `basicConfig` silently no-ops if the root logger already has handlers (the classic "I changed `LOG_LEVEL` and nothing happened" bug). `force=True` (3.8+) tears down existing handlers first. The docstring correctly ties this to *why* it matters here: Streamlit reruns the whole script on every interaction, so `setup_logging()` fires repeatedly in the same process.
- **Library-vs-entrypoint logging convention stated explicitly** — the docstring spells out the rule (entry points call `setup_logging()` once; library modules only ever call `logging.getLogger(__name__)`) instead of leaving it implicit. That's the standard stdlib-recommended convention, written down where a future contributor will actually see it.

**Open questions / follow-ups**:
- ~~Operating mode for the rest of the review~~ → resolved session 2: log findings in the Refactor Backlog; apply only when picked.

---

### `core/` — Tier 0 foundation

**Files**: `__init__.py` (44) · `exceptions.py` (173) · `interfaces.py` (280)

**What it does**: The contracts layer — exception hierarchy, the `Parser` protocol, and the pipeline abstractions (`PipelineStage` ABC, `PipelineContext`, `StageStatus`). Zero internal dependencies (verified), which is exactly right for a `core` package: everything may depend on it, it depends on nothing.

**Abstraction level**: Correct and disciplined. It defines *shapes*, not implementations — implementations live in `ingestion/`. One structural wobble: the `__init__.py` facade exports 9 exceptions, but `DuplicateDocumentError`, `CollectionError`, `EmbeddingSyncError` were added to `exceptions.py` later and never exported — so consumers (`views/ingest.py`, `services/*.py`) import from `core.exceptions` directly. Two inconsistent doors into the same module. Either keep the facade complete (add them to `__all__`) or drop the facade pretense.

**Best-practice notes**:
1. **Exception hierarchy as API** — `MeditationDBError` → `PipelineError`/`DatabaseError`/`CollectionError` → leaf types. Callers choose their granularity (`except ParsingError` vs `except MeditationDBError`). Each docstring lists concrete triggering examples. Textbook.
2. **"Immutable" context that isn't** — `PipelineContext` docstring says immutable; discipline is via `dataclasses.replace` + copying dicts in `mark_stage_*`. But the class is not `frozen=True`, and *the immutability is actually violated in practice*: `EmbeddingStage.execute` (stages.py:253-266) mutates `context.chunks` elements in place (sets `chunk.metadata["uuid"]`, `chunk.id`). `replace()` is shallow — the new context shares the same list and the same `LangchainDocument` objects. Works today because execution is sequential, but the docstring's promise ("stages don't mutate the context") is false, and anything that ever relies on it (retries, parallel stages, comparing before/after contexts) will be bitten.
3. `mark_stage_running` (interfaces.py:174) appears unused — orchestrator notifies via callback instead of mutating context status to RUNNING. Verify + prune.
4. Local `from dataclasses import replace` inside `with_update` — harmless, but no reason not to import at module top.

**Notable Python patterns**:
- **Protocol vs ABC, used side by side, each for the right reason.** `Parser` is a `Protocol` (structural): `URLParser`/`PDFParser` inherit from nothing, yet `ParserFactory.get_parser() -> Parser` type-checks because they match the shape. `PipelineStage` is an ABC (nominal) because it *shares behavior* — `can_run()` and `should_skip()` are concrete default implementations subclasses inherit. Rule of thumb this codebase demonstrates: Protocol when you only need a shape; ABC when you're inheriting logic.
- **Immutable-update pattern** via `dataclasses.replace` — right idea; needs `frozen=True` + awareness that it's shallow (see finding #2).
- **Dependencies declared as data** (`required_stages: List[str]`) so the orchestrator can topo-sort — declarative over imperative wiring.

---

### `db/` — Tier 1

**Files**: `__init__.py` (12) · `schema.py` (155) · `database.py` (182) · `crud.py` (399)

**What it does**: SQLAlchemy ORM models (`Document`, `Chunk`), engine/session lifecycle (`Database` class + backward-compatible module-level helpers), and CRUD classes. The `chunks.uuid ↔ langchain_pg_embedding` link is the bridge between the app DB and the LangChain-managed vector table.

**Abstraction level**: `database.py` is the most architecturally mature file reviewed so far. `schema.py` and `crud.py` are older-generation code (visible strata: `schema.py` still opens with a stale `# file: models.py` comment and tutorial-style "Step 1/Step 2" comments).

**Best-practice notes**:
1. **⭐ The big one: CRUD methods self-commit, breaking the unit of work.** Every mutating method in `DocumentCRUD`/`ChunkCRUD` calls `self.db.commit()`. But `session_scope()` exists precisely to own commit/rollback at the boundary. Concrete failure: `DatabasePersistenceStage.execute` opens *one* `session_scope` and calls `create_chunks_batch` → `update_doc_metadata` → `update_status` → `clear_chunks` — four interior commits. If `update_status` fails, chunks are already durably committed: the "transaction" is an illusion, and rollback in `session_scope` has nothing left to roll back. Correct split: CRUD does `flush()` (get IDs, surface constraint errors), caller's `session_scope` does the single commit. This is also the blocker for atomic enrichment. Backlog #1.
2. **No unique constraint on `documents.file_path`** despite `check_duplicate()` querying it — the dup guard is advisory (race-prone) and unindexed (table scan as the corpus grows). The DB should enforce what the app checks. Backlog.
3. **Legacy declarative style** — `declarative_base()` + `Column(...)`. SQLAlchemy 2.0's `DeclarativeBase` + `Mapped[]`/`mapped_column()` gives typed attributes that mypy actually understands. Medium-effort modernization, high teaching value. Backlog.
4. **`default={}` / `default=[]` on columns** — SQLAlchemy evaluates non-callable defaults once and reuses the object; the safe idiom is `default=dict` / `default=list` (callables). Low-stakes here (values get serialized per-row) but the habit matters.
5. **`Document.chunks` JSONB temp storage** coexists with the `chunks` table — transitional design; `store_chunks`/`clear_chunks` exist but the DAG pipeline no longer routes through them (chunks travel in `PipelineContext`). Candidates for pruning after verification.
6. `crud.py` uses legacy `session.query()`; SQLAlchemy 2.0 style is `select()` + `session.execute()`. Pairs with #3.

**Notable Python patterns**:
- **PEP 562 module-level `__getattr__`** (database.py:176-182) — the module lazily materializes `engine`/`SessionLocal` on attribute access, so old `from db.database import engine`-style code keeps working *without* forcing engine construction at import. Very few people know modules can have `__getattr__`. Worth a blog section on its own.
- **Lazy, injectable resource owner** — `Database` builds its engine on first property access; tests inject `Database(DatabaseSettings(url="sqlite://..."))`; `set_default_database()` is the composition-root override for the process-wide default. This is dependency injection without a framework.
- **Environment-adaptive engine building** — `_build_engine` branches sqlite/remote/local, with the remote branch carrying TCP keepalives + `pool_pre_ping` + recycle for Neon's scale-to-zero. The *reason* lives in `DatabaseSettings.is_remote`'s docstring — behavior and rationale co-located.
- **`@contextmanager` transactional scope** — commit/rollback/close in one place. The pattern is right; it just needs CRUD to stop undermining it (#1).

---

### `observability/` — Tier 1

**Files**: `__init__.py` (2) · `langfuse.py` (196)

**What it does**: Optional Langfuse tracing wrapper for the query layer. `LangfuseTracer.observe(...)` yields a `LangfuseObservationHandle`; `retrieval/` calls `handle.update(...)`/`handle.score(...)` without ever checking whether tracing is on.

**Abstraction level**: Exactly right — a textbook anti-corruption layer. The rest of the codebase depends on this thin wrapper, never on the `langfuse` SDK directly, so SDK version drift (or removal) is contained to one file.

**Best-practice notes**:
1. **The `except Exception` double standard, done correctly.** Every operation here swallows exceptions with a warning log — and that's *right*, because observability must never crash the observed system. Contrast with the pipeline, where failures must propagate. The acceptability of broad catches is a property of the layer's failure budget, not a universal style rule.
2. Dataclass with underscore fields (`_observation`, `_client`) — they show up in `__init__`, `repr`, and `eq`. Works, but `field(repr=False)` or a plain class would be cleaner. Minor.
3. `flush()` on every `observe` exit — a network call per observation; fine for Streamlit, would need buffering under real load.

**Notable Python patterns**:
- **Null Object pattern** — `LangfuseObservationHandle(enabled=False)` is a do-nothing stand-in, so callers have zero `if tracing:` branches. The absence of a feature is modeled as an object, not as a conditional at every call site.
- **Optional dependency handling** — `from langfuse import Langfuse` inside `_build_client`, `ImportError` → informative log + disabled tracer. The app runs fine without the package installed.
- **Duck-typed SDK negotiation** — `getattr(client, "get_trace_url", None)` + `callable(...)` checks, and `_refresh_trace_link` even negotiates the function signature by catching `TypeError` and retrying with an argument. Brittle-looking but deliberate: tolerate SDK API drift rather than pin behavior to one version.
- Same `@lru_cache()` factory-singleton as `get_settings()` — the codebase has a consistent idiom for process-wide lazies.

---

### `ingestion/` — Tier 2 (completed; stages/orchestrator were covered in session 2)

**Files**: `__init__.py` (66) · `parsing.py` (316) · `chunking.py` (525) · `embed.py` (275) · `suttacentral.py` (286) · plus `stages.py` (475) / `orchestrator.py` (607) from session 2

**What it does**: The full parse → chunk → embed pipeline plus the SuttaCentral source adapter. Reading all of it at once makes the codebase's *strata* visible: `embed.py`/`chunking.py` are the oldest layer (own exceptions, own config, `os.getenv`), `parsing.py` is the middle (protocol-aware, but module-level `load_dotenv()`), `suttacentral.py` is the newest and cleanest (constructor-injected fetcher, pure functions, frozen dataclass).

**Verified findings (the big three)**:
1. **⭐ `CHUNKING_*` settings are dead ends.** `config/settings.py` defines `ChunkingSettings` (env-driven), and `chunking.py` defines its own `Config` dataclass with *duplicated defaults*. Grep confirms nothing ever maps `get_settings().chunking` → `Config`; orchestrator and chunker both fall back to `Config()` defaults. Changing `CHUNKING_MAX_SIZE` in `.env` does nothing to the pipeline. Two sources of truth, one of them decorative. Backlog #12.
2. **⭐ Two different `EmbeddingError` classes.** `core/exceptions.py` has one (child of `PipelineError`); `ingestion/embed.py` defines another (child of its own `VectorStoreError`). `EmbeddingStage` imports the core one, but `VectorStoreManager` raises the embed one — so the stage's `except EmbeddingError` branch **never catches the manager's errors**; they fall through to the generic `except Exception`. Works by accident today (both branches mark the stage failed). A shadow exception hierarchy that predates `core/` and was never unified. Backlog #10.
3. **Deprecated `PGVector`.** Both `embed.py` and `retrieval/query.py` import `langchain_community.vectorstores.pgvector` (deprecated), while `langchain-postgres` (its replacement) is in `pyproject.toml` and used nowhere. CLAUDE.md's architecture diagram claims the new one is in use — doc drift. Backlog #14.

**Other findings**:
- **Unit confusion in `_combine_small_chunks`** (chunking.py:354-397): `current_chunk_size` is *words* (`len(page_content.split())`), compared against `min_size` (documented as *chars*, default 700); then `combined_size` starts in words but accumulates `len(next_chunk.page_content)` — *chars* — against `max_size`. The merge heuristics work, but not at the thresholds anyone thinks they configured. Needs a deliberate decision + tests. Backlog #15.
- **Config bypasses** (the pattern from services/ recurs): `VectorStoreConfig.__post_init__` reads `os.getenv("DB_URL")`; `parsing.py` calls `load_dotenv()` at module import (side effect on import!) and `PDFParser` reads `os.environ.get("LLAMAPARSE_API")`. All bypass `config/`. Folded into backlog #7.
- **Four copies of "find the first H1"**: `URLParser._extract_title`, `PDFParser._extract_title`, `SuttaCentralParser._first_h1`, `MarkdownChunker._extract_title`. Backlog #13.
- `MarkdownChunker` takes `text` in its constructor — a per-document throwaway object where a stateless service with `chunk(text, title)` would do (CLAUDE.md documents the latter API — drift again).
- `ingestion/__init__.py` is a *fat facade*: eagerly imports every submodule, so `import ingestion.anything` pays for parsing (dotenv side effect), chunking, embed, and orchestrator. Contrast with `core/`'s lean facade.
- `asyncio.get_event_loop()` in `_split_oversized_chunks` — deprecated since 3.10 inside running loops; should be `get_running_loop()`. Backlog #16.
- Batch embedding **fails fast** on batch errors (raises) — CLAUDE.md says "partial failures are logged but don't halt pipeline." The code is arguably right; the doc is wrong either way.

**Notable Python patterns**:
- **Double-checked locking, three levels deep** (`ThreadSafeEmbeddingsCache`): singleton via `__new__` with a class-level lock; per-model locks so different models can load concurrently while duplicate loads of the *same* model block; a `_locks_lock` guarding the locks dict itself. Genuine concurrency engineering — the lock-free fast path read is safe under the GIL. (Critique: the singleton-via-`__new__` ceremony could be a module-level instance or `@lru_cache` factory — the codebase's own established idiom — but the per-resource locking is the genuinely instructive part.)
- **Sync-to-async bridging**: `loop.run_in_executor(ThreadPoolExecutor, ...)` + `asyncio.gather(*tasks, return_exceptions=True)`, then per-result `isinstance(result, Exception)` with fallback to the unsplit chunk — parallel semantic splitting with per-chunk graceful degradation, order preserved via an index map.
- **Resilience-first chunking**: every step has a fallback (header split fails → whole doc as one chunk; semantic split fails → keep original). Data pipeline philosophy: a worse chunk beats a lost document.
- **Strategy + chain-of-responsibility factory** (`ParserFactory`): ordered `can_parse()` probing; SuttaCentralParser deliberately registered *before* URLParser so `suttacentral.net` URLs route to the API parser instead of fetching an empty SPA shell — order as routing policy, documented in the docstring.
- **Deprecation done right** (`parsing.py`): `warnings.warn(..., DeprecationWarning, stacklevel=2)` — `stacklevel=2` makes the warning point at the *caller's* line, not the shim.
- **Constructor-injected I/O** (`suttacentral.py`): `fetch_json: Callable[[str], dict]` — tests inject a dict-returning fake; no `unittest.mock`, no network. The purest seam in the codebase, and the newest code. Pure functions (`bilara_to_html`, `parse_sutta_ref`, `nikaya_tags`) hold the logic; the class is a thin shell around I/O.
- **Lazy import with stated reason** (`PDFParser.parse`): LlamaParse imported inside the method because the dependency chain is heavy/fragile — the comment says *why*, which is what makes it maintainable.

---

### `retrieval/` — Tier 3

**Files**: `query.py` (461) · `answering.py` (198) · `llm_client.py` (69) · `utils.py` (37)

**What it does**: The RAG query layer. `RetrievalEngine` runs four strategies (similarity / MMR / threshold / hybrid) over the pgvector store; `GroundedAnswerService` synthesizes cited answers via `LLMClient` (a litellm facade); `utils.extract_header_paths` normalizes chunk header metadata across generations of chunker output.

**Abstraction level**: Good layering — engine returns typed `SearchResult`/`SearchResponse`/`SearchTrace` dataclasses, not raw LangChain documents, so `views/` never touches LangChain. `answering.py` is newest-generation quality: injectable client + tracer, explicit context budgets (`max_chunks`, `max_chunk_chars`), and the trace records the *exact* system and user prompts — answers are reproducible after the fact.

**Best-practice notes**:
1. **The sealed boundary re-opened** — `query.py:139` does `os.getenv("DB_URL") or os.getenv("DATABASE_URL")`; `llm_client.py` reads `LLM_PROVIDER`/`LLM_MODEL`/`OLLAMA_BASE_URL` raw (no `LLMSettings` group exists in config at all); `RetrievalEngine` hardcodes collection + embedding-model defaults instead of using `VectorSettings`/`EmbeddingSettings`. This folder was written in parallel with the boundary work and never migrated. Lesson: **boundaries enforced by vigilance decay; encode them as lint rules** — ruff's `flake8-tidy-imports` banned-api (`TID251`) can ban `os.getenv` outside `config/`. Backlog #17.
2. **Test-shaped wart in production** — `_all_chunks: None = None  # kept for test assertions; never populated` exists solely so `test_query_fts.py:23` can assert it's None. Production code should not carry members that exist only for tests. Backlog #18.
3. **Naming drift after implementation swap** — `_bm25_search` is Postgres FTS (`ts_rank`), not BM25; `rank-bm25` remains in pyproject with zero imports. The comment admits the swap; the name and dependency didn't follow. Backlog #20, #21.
4. **FTS computes `to_tsvector` per row per query** — no generated tsvector column, no GIN index → sequential scan that re-parses every chunk's text on every hybrid search. Fine at hundreds of chunks; not at 100k (the project's stated scale target). Pairs naturally with the #2 migration. Backlog #19.
5. **Score semantics need an audit** — `SearchResult.score` docstring says "higher = more relevant", but community-PGVector's `similarity_search_with_score` returns *distance* (lower = better), while hybrid returns RRF scores and threshold uses normalized relevance. Three strategies, three different score meanings, one field and one docstring. Classic vector-store trap. Backlog #20.
6. `llm_client.py` mutates global `litellm.api_base` for ollama — process-wide state; two clients with different providers in one process would fight. Acceptable now, worth a comment.

**Notable Python patterns**:
- **Dictionary dispatch** — `strategy_map = {RetrievalStrategy.SIMILARITY: self._similarity_search, ...}` then `strategy_map[strategy](...)`: the enum→method table replaces an if/elif chain and makes "add a strategy" a one-line diff.
- **Weighted Reciprocal Rank Fusion** — clean ~20-line implementation of a real IR algorithm (`score = Σ weight_i/(rrf_k + rank_i)`), with `_doc_key` providing a stable dedup key (uuid, else content SHA-256) so the same chunk arriving via both retrievers merges its scores.
- **Use the database you already have** — hybrid search's lexical leg is Postgres `ts_rank` instead of an in-memory BM25 index: no index rebuild on every process start, no RAM cost, one fewer dependency. Boring-tech win.
- **Trace-first design** — every search returns a `SearchTrace` (params, timing, strategy notes, Langfuse ids) and every answer an `AnswerTrace` including full prompts. Observability as part of the return type, not a side channel.
- **Failure-path telemetry** — `except: observation.update(status failed); raise` — the trace records the failure *and* the exception still propagates. Contrast with swallowing.

---

## Refactor Backlog

Findings logged during review; applied only when Himanshu picks them. Ordered by value.

| # | Refactor | Where | Effort | Why |
|---|----------|-------|--------|-----|
| 1 | ✅ **Applied (session 3)** — commit ownership moved out of CRUD (`flush()` only; `session_scope` owns the commit); call-site audit confirmed all usage already inside scopes; redundant interior `session.commit()` calls removed from `ParsingStage`/orchestrator | `db/crud.py`, `ingestion/stages.py`, `ingestion/orchestrator.py` | Medium | Restores real transactions; prerequisite for atomic enrichment. Contract test: `tests/test_crud_transaction_ownership.py` |
| 2 | ✅ **Applied (session 6)** — dupe check on live Neon: 0 duplicates; unique index `ix_documents_file_path` created via migration `b7c9d1e3f5a7` and applied; schema.py mirrors it | `db/schema.py`, `alembic/` | Small | DB now enforces the dup guard |
| 3 | ✅ **Applied (session 3)** — `PipelineContext` is `frozen=True`; `EmbeddingStage` enriches copies instead of mutating shared chunks | `core/interfaces.py`, `ingestion/stages.py` | Small–Medium | Immutability promise now enforced. Contract test: `tests/test_pipeline_context_immutability.py` |
| 4 | ✅ **Applied (session 4)** — deleted `_get_*` helpers, vestigial `validate_max_size`, `store_chunks`, `serialize_docs`/`deserialize_docs`, `mark_stage_running` (all zero-call-site verified). Kept `clear_chunks` (live) and the `Document.chunks` column (needs a migration to drop) | `config/`, `db/`, `core/`, `ingestion/` | Small | Less to read for future public sharing |
| 5 | ✅ **Applied (session 4)** — facade now exports the full hierarchy incl. new `VectorStoreError`/`DatabaseConnectionError`. Test: `tests/test_core_exports.py` | `core/__init__.py` | Tiny | One consistent import door |
| 6 | ✅ **Applied (session 4)** — invariant on `ChunkingSettings.model_post_init`; all four env-var fallback validators replaced with `AliasChoices` + `populate_by_name=True`. Note learned: alias order IS precedence order, and dotenv values participate (DB_URL in .env beats DATABASE_URL in the environment) | `config/settings.py` | Small | Invariants live with their data |
| 7 | ✅ **Applied (session 4, with #11)** — removed raw env reads from `services/ingestion_service.py`, `VectorStoreConfig.__post_init__`, `PDFParser`; deleted `parsing.py`'s module-level `load_dotenv()` side effect. Tests: `tests/test_config_boundary.py` (hermetic via chdir to tmp) | `services/`, `ingestion/` | Small | config/ is the only env boundary |
| 8 | ⏸ **Deferred** (partially: `default=dict` done in #9) — `DeclarativeBase` + `Mapped[]` migration is a dedicated PR; will eliminate most of the 71 remaining mypy errors | `db/schema.py`, `db/crud.py` | Medium | Typed ORM, mypy-checkable, current idiom |
| 9 | ✅ **Applied (session 4)** — stale comments removed; also `default={}`/`default=[]` → `default=dict`/`default=list` on columns | `db/schema.py` | Tiny | Readability for public sharing |
| 10 | ✅ **Applied (session 4)** — embed's local hierarchy deleted; `VectorStoreError`/`DatabaseConnectionError` now live in core, `EmbeddingError` is one class. The stage's specific except branch is provably live: `tests/test_exception_unification.py` asserts manager errors are recorded verbatim (no 'Unexpected error:' prefix) | `ingestion/embed.py`, `core/exceptions.py` | Small–Medium | One hierarchy, live catch branches |
| 11 | ✅ **Applied (session 4, as part of #7)** | `ingestion/` | Small | Single config boundary |
| 12 | ✅ **Applied (session 4)** — `Config.from_settings()` bridges `CHUNKING_*`/`EMBEDDING_HUGGINGFACE_MODEL` into the chunker; orchestrator defaults to it. Tests: `tests/ingestion/test_chunking_config.py` | `ingestion/chunking.py`, orchestrator | Small–Medium | Config that actually configures |
| 13 | ✅ **Applied (session 4)** — `ingestion/markdown_utils.py:extract_first_h1()`, all 4 call sites converted. Tests: `tests/ingestion/test_markdown_utils.py` | `ingestion/` | Tiny | One implementation |
| 14 | ⏸ **Deferred** — needs a data-compat plan: langchain-postgres uses a different table layout/driver (psycopg3), so existing embeddings must be verified/migrated against a live DB | `ingestion/embed.py`, `retrieval/query.py` | Medium | Off deprecated API |
| 15 | ✅ **Applied (session 6)** — Himanshu chose chars; `_combine_small_chunks` measures characters everywhere. Tests: `tests/ingestion/test_chunking_units.py` (cases where words- and chars-interpretations disagree). Existing 5-doc corpus left as-is; re-ingest optional | `ingestion/chunking.py` | Small–Medium | Thresholds mean what config says |
| 16 | ✅ **Applied (session 4)** | `ingestion/chunking.py` | Tiny | Deprecated pattern |
| 17 | ✅ **Applied (session 6)** — `LLMSettings` added; retrieval + services + orchestrator `__main__` all resolve via settings. **Policy established: leaf components read narrow settings groups directly (`DatabaseSettings()`, `ParsingSettings()`, `LLMSettings()`); only composition roots use cached `get_settings()`** — discovered because resolving one key via the composed root forces validation of every group. TID251 ban on `os.getenv` now active in ruff (config/ and scripts/ excepted) | `retrieval/`, `config/`, `pyproject.toml` | Small–Medium | Boundary is now a lint rule |
| 18 | ✅ **Applied (session 6)** — attribute removed; test now asserts the executed SQL targets `chunk_text_tsv` (behavior, not internals) | `retrieval/query.py` | Tiny | No test-shaped warts |
| 19 | ✅ **Applied (session 6)** — `chunks.chunk_text_tsv` (GENERATED ALWAYS ... STORED) + GIN index, migration `b7c9d1e3f5a7` applied to Neon (24/24 chunks populated, FTS verified); `_fts_search` queries the column | `db/schema.py`, `alembic/`, `retrieval/query.py` | Small–Medium | Index-backed FTS |
| 20 | ✅ **Applied (session 6, doc-level)** — per-strategy score semantics documented on `SearchResult.score` (SIMILARITY=distance/lower-better; HYBRID=RRF/higher-better; MMR/THRESHOLD=None); `_bm25_search` renamed `_fts_search`. Normalizing to one scale deferred until a consumer needs it | `retrieval/query.py` | Small | One field, documented meanings |
| 21 | ✅ **Applied (session 6)** — removed via `poetry remove --lock` | `pyproject.toml` | Tiny | Dead dependency |
| 22 | Bump transitive `semantic-router` ≥0.1.15 (locked 0.1.12 is yanked re CVE-2026-42208; root litellm pin already blocks the attack vector, so low urgency) | `pyproject.toml` | Tiny | Clean lockfile |
| 23 | `.env` hygiene: `DB_URL` still points at the decommissioned Supabase instance (connection refused); app-facing URL should move to `NEON_POOLER_URL`'s value. **User action — I don't edit credentials files** | `.env` | Tiny | App config points at a dead DB |
