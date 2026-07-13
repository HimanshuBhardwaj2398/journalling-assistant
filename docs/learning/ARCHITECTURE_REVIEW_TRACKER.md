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
- [ ] `observability/`
- [ ] `ingestion/` *(partially done: `stages.py` + `orchestrator.py` reviewed in session 2 for the strategic questions; still to read properly: `chunking.py`, `parsing.py`, `embed.py`, `suttacentral.py`, `__init__.py`)*
- [ ] `retrieval/`
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
- Committed on branch `refactor/state-ownership` and pushed.
- Next: `observability/`, then finish `ingestion/`.

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

## Refactor Backlog

Findings logged during review; applied only when Himanshu picks them. Ordered by value.

| # | Refactor | Where | Effort | Why |
|---|----------|-------|--------|-----|
| 1 | ✅ **Applied (session 3)** — commit ownership moved out of CRUD (`flush()` only; `session_scope` owns the commit); call-site audit confirmed all usage already inside scopes; redundant interior `session.commit()` calls removed from `ParsingStage`/orchestrator | `db/crud.py`, `ingestion/stages.py`, `ingestion/orchestrator.py` | Medium | Restores real transactions; prerequisite for atomic enrichment. Contract test: `tests/test_crud_transaction_ownership.py` |
| 2 | Unique constraint + index on `documents.file_path` (Alembic migration) | `db/schema.py`, `alembic/` | Small | Dup guard currently advisory + unindexed |
| 3 | ✅ **Applied (session 3)** — `PipelineContext` is `frozen=True`; `EmbeddingStage` enriches copies instead of mutating shared chunks | `core/interfaces.py`, `ingestion/stages.py` | Small–Medium | Immutability promise now enforced. Contract test: `tests/test_pipeline_context_immutability.py` |
| 4 | Delete dead code: `_get_*` helpers in settings.py, vestigial `validate_max_size`, likely-unused `store_chunks`/`clear_chunks` + `Document.chunks` column, `mark_stage_running` | `config/`, `db/`, `core/` | Small | Less to read for future public sharing |
| 5 | Complete `core/__init__.py` exports (3 missing exceptions) | `core/__init__.py` | Tiny | One consistent import door |
| 6 | Move `max_size > min_size` check onto `ChunkingSettings.model_post_init`; env aliases via `AliasChoices` | `config/settings.py` | Small | Invariants live with their data |
| 7 | Fix config bypass: `services/ingestion_service.py:29` reads `os.getenv` directly | `services/` | Tiny | Preserve the config boundary |
| 8 | SQLAlchemy 2.0 modernization: `DeclarativeBase` + `Mapped[]`, `select()` over `session.query()`; `default=dict` not `default={}` | `db/schema.py`, `db/crud.py` | Medium | Typed ORM, mypy-checkable, current idiom |
| 9 | Stale comments: `# file: models.py`, tutorial-style "Step 1/2" comments | `db/schema.py` | Tiny | Readability for public sharing |
