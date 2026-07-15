# Learning to Read My Own Codebase Like an Architect

*A running journal written while doing a folder-by-folder architecture review of the meditation-assistant codebase. Candid and code-specific for now — this gets a genericizing/polish pass before it goes anywhere public. Companion doc: [ARCHITECTURE_REVIEW_TRACKER.md](ARCHITECTURE_REVIEW_TRACKER.md), which has the raw per-folder notes this draws from.*

## Why this exists

[To fill in once there's enough material to know the actual throughline — the honest version will probably be something like "I wanted to get better at judging my own architecture instead of just shipping features," but let's see what the entries actually say before committing to a framing.]

## How to read this

Each entry covers one folder: what it's for, whether the abstraction is doing its job, and the Python pattern(s) inside it that were worth stopping on. Entries are written in review order (roughly bottom-up through the dependency stack — foundations first), which may not be the best reading order for someone else. A reordering/editing pass happens once there's a full draft.

## Entries

### 1. `config/` — the folder whose whole job is to be boring

Every real app needs one folder whose entire job is to be boring, and boring is the highest compliment you can pay it. `config/` here is three files, about 340 lines, and its job is to be the *only* place in the codebase allowed to call `os.getenv`. I grepped to check rather than take it on faith — it's true. Every other module gets typed, validated settings instead of string-soup pulled from the environment at random call sites. That's the abstraction working exactly as intended.

A few things in here were worth stopping on.

**Cache the factory, not the object.** The obvious way to write a settings singleton is a module-level `settings = Settings()` at import time. This codebase does something better: a plain function wrapped in `@lru_cache()`.

```python
@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

The difference matters more than it looks. A module-level instance loads and validates the moment anything imports the module — including validation failures, which now happen at *import* time, in whatever order Python happens to import things, which is a miserable place to debug a missing environment variable. The cached function is lazy: nothing is built until the first call. It's also swappable — tests can call `get_settings.cache_clear()` and get a fresh read. And it's the exact shape FastAPI's `Depends(get_settings)` convention expects, for free, if this project ever grows an API layer. The one trap: it's a *process-lifetime* cache, so changing an env var mid-process is invisible until you clear it. The tests in this repo dodge the whole issue by never calling `get_settings()` at all — they construct `Settings()` directly, which reads the environment fresh every time. Worth keeping that habit.

**There's a first-class way to alias an env var, and it isn't a validator.** Several settings need to accept two different env var names for backward compatibility — `DB_URL` or the more standard `DATABASE_URL`, `HF_TOKEN` under its own name, and so on. The pattern used here is a `field_validator(mode="before")` that manually falls back to `os.getenv("DATABASE_URL")` if the primary value is empty. It works, but Pydantic v2 has a feature built for exactly this: `Field(validation_alias=AliasChoices("DB_URL", "DATABASE_URL"))`. Same outcome, no custom method, no `os.getenv` call hiding inside a validator body. General lesson: before reaching for a validator, check whether the field system already has a name for what you're doing — aliasing is common enough that it usually does.

**Config objects are allowed to have opinions.** `DatabaseSettings` doesn't just hold a URL — it has an `is_remote` property that parses the hostname and decides whether this is a managed Postgres instance. `LangfuseSettings` has `is_configured`, which collapses "is tracing enabled AND do we have both keys" into one question instead of every call site re-deriving it. Small thing, but it's the difference between a config module and a config *object* — the latter can carry a little behavior without becoming a god object, as long as what it carries is genuinely about answering questions from its own data.

**An invariant should live where the data lives.** `ChunkingSettings` has a rule — `max_size` must exceed `min_size` — but the actual check isn't on `ChunkingSettings`. It's bolted onto the parent `Settings.model_post_init`, because (per a comment left in the code) a single-field validator "can't access other fields." True for `field_validator`, not true for `model_post_init`, which works at any nesting level, including on `ChunkingSettings` itself. As written, if you ever construct `ChunkingSettings(max_size=1, min_size=100)` on its own — in a test, say — nothing stops you. The rule only fires if you go through the parent. Worth remembering: pydantic's cross-field hook isn't a root-only feature, so put the check as close to the data it's protecting as possible.

**The logging trick nobody knows about.** `logging_config.py` calls `logging.basicConfig(..., force=True)`. Most people don't know `force` exists, and it's the reason `basicConfig` doesn't silently no-op — by default, `basicConfig` refuses to do anything if the root logger already has handlers attached, which is *the* classic explanation for "I set `LOG_LEVEL` and nothing changed." `force=True` (3.8+) tears down existing handlers before reapplying. The comment in the code explains exactly why it's needed here: Streamlit reruns the entire script top-to-bottom on every UI interaction, so `setup_logging()` gets called over and over in the same process, and without `force=True` only the first call would ever count.

**The unglamorous finding: dead code hides best inside "backward compatibility."** Four functions at the bottom of `settings.py` — `_get_db_url`, `_get_voyage_api_key`, `_get_llamaparse_api`, `_get_hf_token` — are commented as existing for backward compatibility. Grepping the whole repo: zero call sites. Not one. The label "backward compatibility" is exactly what makes code like this survive cleanups it would otherwise fail — it *sounds* load-bearing, so nobody wants to be the one who deletes it. Worth treating "kept for backward compatibility" as a claim to verify, not a reason to skip verifying.

### 2. `core/` — Protocol and ABC in the same codebase, and when each is right

Python gives you two ways to say "things of this kind must have these methods," and most codebases pick one and use it everywhere. This one uses both — and, unusually, uses each where it's actually the right tool. That contrast is the clearest explanation of the difference I've seen in real code.

`Parser` is a `typing.Protocol`. The concrete parsers — `URLParser`, `PDFParser` — inherit from *nothing*. They just happen to have `can_parse()` and `parse()` methods, and that's enough: `ParserFactory.get_parser() -> Parser` type-checks fine, because Protocol is structural typing — "if it has the shape, it counts." No registration, no base class import, no coupling. A third-party parser could be written in a module that has never heard of `core/` and it would slot in.

`PipelineStage`, meanwhile, is an old-fashioned ABC — and that's correct too, for a reason that has nothing to do with taste: **it ships behavior**. `can_run()` (checks that declared dependencies completed) and `should_skip()` (skips already-completed stages) are concrete methods every stage inherits. A Protocol can't give you that; it's a shape, not an implementation. So the rule of thumb this codebase demonstrates: *Protocol when you only need a shape; ABC when subclasses should inherit logic.*

The second lesson from `core/` is less flattering: **immutability by convention isn't immutability**. `PipelineContext` documents itself as an "immutable context" — stages are supposed to produce new contexts via `with_update()` (a wrapper around `dataclasses.replace`) rather than mutating. The discipline is real: the `mark_stage_*` methods carefully copy their dicts before updating. But the dataclass isn't `frozen=True`, so nothing *enforces* any of it. And sure enough, one stage quietly breaks the promise: the embedding stage reaches into `context.chunks` and mutates each chunk in place — setting UUIDs into their metadata dicts. It works, because execution is sequential and nobody compares before/after contexts. But `dataclasses.replace` is a *shallow* copy — the "new" context shares the same list object and the same chunk objects as the old one. The day anything relies on the documented immutability (retries, parallelism, diffing contexts), this becomes a genuinely nasty bug, because the docstring says it can't happen.

Two takeaways I want to keep: (1) if you claim immutability, make the compiler-ish machinery enforce it — `frozen=True` costs one line; (2) even then, frozen protects the *fields*, not the contents of mutable fields. A frozen dataclass holding a list is a locked door next to an open window. True defensive immutability means tuples over lists, or copying at the boundary — and it's fine to *not* pay that cost, as long as you stop writing "immutable" in the docstring.

One more small thing: exception hierarchies are API design. `core/exceptions.py` builds a tree — `MeditationDBError` at the root, `PipelineError` and `DatabaseError` as branches, `ParsingError`/`ChunkingError`/`DocumentNotFoundError` as leaves. The tree shape is what lets callers choose their blast radius: a UI layer catches `MeditationDBError` ("something of ours went wrong, show a friendly message"), while a retry loop catches only `EmbeddingError`. Flat exception modules throw that choice away. The trap to watch: the package's `__init__.py` facade drifted — three exceptions added later never made it into `__all__`, so half the codebase imports from `core` and half from `core.exceptions`. Facades are a commitment; either keep them complete or don't have them.

### 3. `db/` — who owns the transaction?

This folder contains both the most sophisticated code in the project and its one real architectural bug, which makes it a perfect case study in how codebases are sedimentary — layers written at different skill levels coexisting in one package.

**The bug first, because the lesson generalizes.** There's a tidy context manager, `session_scope()`, whose whole reason to exist is transactional discipline: open a session, yield it, commit if the block succeeds, roll back if it raises. Classic unit-of-work. And then every single mutating method in the CRUD classes… calls `self.db.commit()` itself. Create chunks — commit. Update metadata — commit. Update status — commit.

Put those together and watch what happens in the persistence stage of the pipeline, which opens *one* `session_scope` and makes four CRUD calls inside it, clearly expecting all-or-nothing. What it actually gets: four separate durable commits. If call three fails, calls one and two are already permanent — the rollback in `session_scope` fires and rolls back nothing, because everything before the failure was already committed. The transaction boundary is decorative.

The principle: **in any layered design, exactly one layer owns the transaction, and it's the one that knows the business operation's boundaries.** CRUD methods can't know whether they're a whole operation or one step of five — so they must not commit. The correct division of labor is: CRUD calls `flush()` (pushes SQL so IDs materialize and constraint violations surface early, but stays inside the transaction), and the caller's `session_scope` performs the single commit. This is also, not coincidentally, the thing blocking future features here: "update fifty chunks with generated tags plus the parent document's summary, atomically" is impossible until the interior commits go.

**Now the sophisticated part, because it deserves the spotlight.** `database.py` solves a problem every Python service hits: module-level resources (DB engines, clients) that get built *at import time*, which makes importing the module require a configured environment — the reason so many test suites can't even import application code without a database running. The solution here has three pieces worth stealing:

1. A `Database` class that owns engine + session factory but builds them lazily, on first property access. Constructing `Database(settings)` is free; nothing touches the network until you use it. Tests inject `Database(DatabaseSettings(url="sqlite://..."))` and never see Postgres.
2. A process-wide default instance, also lazy, with a `set_default_database()` override — so an entrypoint (the "composition root") can redirect every legacy call site in one line, without threading a database object through the whole call graph.
3. The obscure gem: **module-level `__getattr__`** (PEP 562). Old code does `from db.database import engine`. Normally that forces the engine to exist at import. But since Python 3.7, a *module* can define `__getattr__(name)`, called when a normal attribute lookup fails — so `engine` isn't defined anywhere at module level, and the function builds-on-demand only when someone actually reaches for it. Backward compatibility preserved, import-time side effects eliminated. Very few Python developers know modules can do this.

The strata are visible to the naked eye, too: `schema.py` still opens with a stale `# file: models.py` comment and tutorial-style "Step 1: Set up the Base Class" comments from whenever it was first written, uses the legacy `declarative_base()`/`Column` style (SQLAlchemy 2.0's `Mapped[]`/`mapped_column` gives you ORM attributes that type-checkers actually understand), and has `default={}` on columns — a shared-mutable-object habit that `default=dict` fixes for free. None of these are emergencies. But when the plan is to share code publicly, this kind of sediment is what readers trip on first, because it's the first thing on the page.

One schema-level lesson worth its own line: **the database should enforce what the application checks.** There's a `check_duplicate(file_path)` guard in the ingestion flow — but no unique constraint on that column. So the guard is advisory: two concurrent ingests of the same URL pass the check simultaneously and both insert. Any invariant you'd write an `if` for in the app is a candidate for a constraint in the schema; the constraint is the one that can't be raced.

### 4. Who owns state change? (a case study in two fixes)

*This entry documents an actual refactor we shipped, not just an observation — the two bugs below were found during the reviews in entries 2 and 3, and fixed together because they turned out to be the same bug wearing two costumes.*

Here's the question that connects them: **for every piece of state in a system, exactly one party should own the right to change it — and something mechanical should stop everyone else.** Both bugs were cases where a well-designed ownership boundary existed on paper and was quietly bypassed in practice. Neither had ever caused a visible failure. That's precisely what made them architecture bugs rather than ordinary bugs: they don't fail, they wait.

#### Costume one: the transaction that wasn't

The database layer had a textbook unit-of-work context manager:

```python
@contextmanager
def session_scope(self):
    session = self.session_factory()
    try:
        yield session
        session.commit()        # ONE commit, at the operation boundary
    except Exception:
        session.rollback()      # or NONE, if anything failed
        raise
```

The design statement: *whoever opens the scope defines the atomic operation.* And then every mutating CRUD method — `create_document`, `update_status`, `create_chunks_batch`, all ten of them — called `self.db.commit()` internally. The helper layer was unilaterally ending transactions it didn't own.

Watch the collision in the pipeline's persistence stage, which opens one scope and clearly intends one atomic operation:

```
with session_scope() as session:      # BEGIN — "make this all-or-nothing"
    create_chunks_batch(...)          #   COMMIT ①  now permanent
    update_doc_metadata(TOC)          #   COMMIT ②  now permanent
    update_status(COMPLETED)          #   💥 fails (connection drop, say)
                                      # session_scope: ROLLBACK →
                                      #   rolls back an EMPTY transaction.
                                      #   ① and ② are already carved in stone.
```

The database ends up in a state the code believes is impossible: chunks persisted, TOC saved, document status stranded mid-pipeline. The rollback fired and protected nothing.

The fix is small and the principle is big. SQLAlchemy has a underused middle ground between "staged in memory" and "permanently committed": `flush()` sends the SQL — so primary keys materialize and constraint violations surface early — **but the transaction stays open and rollback still works.** So: CRUD methods flush; the caller's `session_scope` performs the single commit.

```python
# Before: the helper decides the transaction is over
doc.status = status
self.db.commit()
self.db.refresh(doc)

# After: the helper stages work; the scope owns the boundary
doc.status = status
self.db.flush()
```

The callers didn't change *at all* — they were already written as if transactions worked. They just started getting the atomicity they'd been promised. (Bonus: `create_chunks_batch` had been doing `commit()` then a `refresh()` per chunk — one `SELECT` round-trip per chunk, purely to reload state the commit had expired. `flush()` assigns the IDs in a single round-trip; the whole refresh loop got deleted.)

The layering rule underneath: **mechanism below, policy above.** A CRUD method knows *how* to write a row; only the caller knows whether that write is a whole operation or step two of five. The layer with the business context owns the boundary.

#### Costume two: the immutable object that wasn't

The ingestion pipeline passes a `PipelineContext` through its stages, documented as immutable: stages return new contexts via `with_update()` (a wrapper over `dataclasses.replace`) instead of editing the one they received. Immutability here isn't aesthetics — the orchestrator's resume/skip logic reads state off the context, and retries or parallel stages are only safe if "the context after stage N" is a fixed fact.

Two problems. First, nothing enforced it — the dataclass wasn't `frozen`, so the immutability was a docstring. Second, and more instructive: `dataclasses.replace` is **shallow**. It builds a new context, but every field you didn't override is shared by reference — same `chunks` list, same chunk objects, same metadata dicts. And sure enough, one stage was exploiting that: the embedding stage reached through the context and mutated every chunk in place (stamping UUIDs into their metadata). After it ran, *every context that had ever referenced those chunks* showed the post-embedding state. The "context as it was before embedding" no longer existed anywhere in memory.

The fix, again, is about assigning ownership. The context became `frozen=True` (attribute assignment now raises `FrozenInstanceError` — one line, and `replace()` still works because it constructs rather than assigns). And the embedding stage now pays for its own mutations by copying what it changes:

```python
# Before: enrich the shared objects in place
for chunk in context.chunks:
    chunk.metadata["uuid"] = chunk_uuid          # visible to every holder
return context.mark_stage_completed(self.name)   # chunks field: same list!

# After: enrich copies; the input context is untouched
metadata = dict(chunk.metadata)
metadata["uuid"] = chunk_uuid
enriched.append(Document(id=chunk_uuid, page_content=chunk.page_content,
                         metadata=metadata))
...
return context.with_update(chunks=enriched).mark_stage_completed(self.name)
```

The cost is a few hundred small dict copies per document — unmeasurable next to the embedding API calls in the same function. The rule: **whoever mutates, copies** — and remember that `frozen=True` locks the fields, not the contents of mutable fields. A frozen dataclass holding a list is a locked door next to an open window; the copy at the mutation site is what closes the window.

#### How the fixes were driven (and why order mattered)

Both went in test-first. The tests state the *contracts*, not the implementations:

```python
# "No CRUD method may commit — the enclosing session_scope owns that."
operation(mock_session)
mock_session.commit.assert_not_called()

# "The stage must not touch the chunks it was given."
result = await stage.execute(context)
assert input_chunks[0].metadata == {}      # originals pristine
assert result.chunks is not context.chunks # enrichment lives on copies
```

Watching all fifteen fail first proved they actually pin the behavior (a test that passes immediately proves nothing). Then the implementation turned them green — with the existing 96 tests confirming nothing else moved. The contract tests now stand guard: the day someone adds a convenient little `commit()` to a CRUD method, a test with the transaction-ownership rationale in its docstring fails and explains why.

#### The takeaway question

For any state in your system — a config object, an ORM session, a pipeline context, a cache — ask three questions: *Who may change this? At what moment? And what mechanically prevents anyone else?* If the answer to the third is "a docstring" or "convention," you don't have a boundary, you have a suggestion. Both of these bugs lived in the gap between a documented rule and an enforced one — and both fixes were less about writing new code than about making the existing design tell the truth.

### 5. `observability/` — model the absence of a feature as an object

Tracing (Langfuse, in this codebase) is the kind of feature that's optional three ways at once: the package might not be installed, the API keys might not be set, and any individual network call might fail. The naive implementation of "optional" is an `if tracing_enabled:` check at every call site — dozens of branches, all of which must stay in sync.

This module does it with the **Null Object pattern** instead, and it's the cleanest implementation of it I've seen in a small codebase. `tracer.observe(...)` always yields a handle. If tracing is configured, the handle wraps a live Langfuse observation; if not, it yields `LangfuseObservationHandle(enabled=False)` — an object whose `update()` and `score()` methods simply return. The calling code in the retrieval layer is identical either way: not one `if` about whether tracing is on. The absence of the feature is *an object that does nothing*, rather than a conditional smeared across every consumer.

Two more things worth keeping from this file:

**Broad `except Exception` is a layer property, not a style rule.** Every operation in this module swallows exceptions with a `logger.warning`. In the ingestion pipeline that would be a bug — failures there must propagate and mark documents FAILED. Here it's *correct*, because the one inviolable rule of observability is that it must never take down the thing it's observing. Same construct, opposite verdicts, and the difference is the layer's failure budget. Style guides that just say "never catch bare Exception" miss this.

**Keep the third-party SDK behind your own thin wall.** Nothing outside this file imports `langfuse`. The wrapper even handles the SDK not being installed (`ImportError` → informative log, tracing off) and negotiates API differences defensively (`getattr(client, "get_trace_url", None)`, retry with an argument on `TypeError`). That's an anti-corruption layer: when the SDK breaks its API — observability SDKs love doing this — the blast radius is one file.

### 6. `ingestion/` — reading your own repo as an archaeological dig

Reading all seven files of the ingestion package in one sitting produced a lesson no single file could: **a codebase has strata, and you can date them.** `embed.py` and `chunking.py` are the oldest layer — they define their own exception classes and their own config, and read `os.getenv` directly, because they predate `core/` and `config/`. `parsing.py` is the middle period — it implements the `Parser` protocol from `core`, but still calls `load_dotenv()` at module import. `suttacentral.py` is the newest — injected dependencies, pure functions, frozen dataclasses, docstrings that explain *why*. Same author, months apart, and the growth is visible in the rock face. Once you can see the strata, you know exactly what "modernize this codebase" means: make the old layers look like the newest one.

The dig turned up three real fossils, each verified by grep rather than assumed:

**Config that configures nothing.** `config/settings.py` defines `ChunkingSettings`, loaded from `CHUNKING_*` env vars, documented in the project README. `chunking.py` defines its own `Config` dataclass with the same fields and duplicated defaults. Nothing anywhere maps one to the other — the pipeline always runs on `Config()` defaults. Set `CHUNKING_MAX_SIZE=5000` in `.env` and precisely nothing happens. The lesson generalizes: **every config value should be traceable from env var to the line that consumes it**, and the check is mechanical — grep the setting's name and follow it. Duplicated config schemas are where this dies quietly, because both copies look authoritative.

**Two exceptions with the same name.** `core/exceptions.py` has an `EmbeddingError`. So does `ingestion/embed.py` — a different class, different hierarchy, same name. The embedding stage imports the core one and writes `except EmbeddingError:` — but the vector store manager it calls raises the *other* one, so that handler never fires; every manager failure falls through to the generic `except Exception` below it. Nothing crashes — both branches happen to do the same thing — which is why it's survived. A dead `except` branch is worse than no branch: it documents handling that isn't happening. When a codebase grows a central exception hierarchy, the migration isn't done until the old local hierarchies are *deleted*, not just superseded.

**Units that don't agree.** The chunk-merging logic measures the current chunk in *words* (`len(text.split())`), compares that against a threshold documented in *characters* (`min_size: 700`), then accumulates a running total that starts in words and adds character counts. The merging behaves sensibly-ish anyway — which is exactly the problem, because nobody's configured thresholds mean what they think. Mixed units survive wherever a number is just an `int`; the boring fixes (name variables `min_chars`/`word_count`, or use typed wrappers) are cheaper than the archaeology needed later to figure out what a threshold was supposed to mean.

Not everything in the dig was a fossil — two patterns are worth stealing:

**Per-resource locking done properly** (`ThreadSafeEmbeddingsCache`): a singleton holding one lock per model name, plus a lock guarding the lock dict itself. Loading two *different* embedding models can proceed concurrently; two threads loading the *same* model serialize, with a double-check inside the lock so the loser uses the winner's result. And the read path checks the cache with no lock at all — safe in CPython because the GIL makes single dict reads atomic. This is the full double-checked-locking idiom, correctly built, in a codebase that mostly doesn't need threads — worth studying precisely because most Python engineers never see it done right.

**Inject the fetch function, not a mock** (`suttacentral.py`): the parser takes `fetch_json: Callable[[str], dict]` in its constructor, defaulting to a real HTTP fetcher. Tests pass a lambda returning canned dicts — no `unittest.mock`, no patching, no network. All the interesting logic (reconstructing HTML from the bilara segment layers, parsing sutta references, deriving nikaya tags) lives in pure functions that take dicts and return values. The class is a thin shell around I/O; the logic is testable without it. Newest file in the package, and it shows — this is the standard the older strata should be brought up to.

### 7. Paying down the backlog — and what a "cleanup PR" teaches that reviews don't

After three sessions of finding things, we spent one fixing them: nine backlog items in a single test-first batch (dead code deletion, completing the core facade, moving the invariant onto `ChunkingSettings`, replacing four hand-rolled env-fallback validators with `AliasChoices`, sealing every config bypass, unifying the duplicate exception hierarchies, wiring `CHUNKING_*` env vars to the chunker at last, deduplicating the H1 extractor, and one deprecated asyncio call). Sixteen new tests, all watched failing first; 128 passing after; one *fewer* mypy error than baseline. Three lessons from the fixing side that the reviewing side never surfaces:

**Cleanups need RED tests too.** It's tempting to treat "delete dead code, swap a validator for an alias" as too mechanical to test-drive. But the RED run caught exactly what it exists to catch: my assumption about how `AliasChoices` resolves was wrong, and I only found out because a test failed in a way I didn't predict. Which leads to —

**Alias order is precedence order — across sources.** In pydantic-settings, `AliasChoices("DB_URL", "DATABASE_URL")` doesn't mean "check the environment for DB_URL, then the environment for DATABASE_URL." The dotenv file participates in resolution, and the *first-listed alias wins wherever it's found*: a `DB_URL` sitting in `.env` beats a `DATABASE_URL` exported in the actual shell. Discovered empirically when a test asserted the opposite and the project's real `.env` leaked into it. Two takeaways: order your aliases by intended precedence, not alphabetically or by legacy-ness; and —

**Tests that read config must be hermetic.** The failing tests weren't wrong about the code — they were accidentally testing my development machine's `.env` file. The fix was one line: `monkeypatch.chdir(tmp_path)` so the settings loader finds no dotenv file, plus clearing the `lru_cache` on both sides of the test. Any test that exercises configuration resolution should run in a directory it controls; otherwise it passes on your machine and fails on CI, or worse, the reverse.

The items we *didn't* do are as instructive as the ones we did. The unique-constraint migration needs a live database (you dedup existing rows before you add the constraint that forbids them). The PGVector modernization needs a data-compatibility plan (the replacement library uses a different table layout — swapping the import silently orphans every existing embedding). And the words-vs-chars unit fix is deferred not because it's hard but because it *changes chunking behavior*: fix the units and every future document chunks differently from the existing corpus unless you re-ingest everything. A backlog isn't a todo list to be zeroed; each item carries a blast radius, and "small code change" and "small change" are different things.

### 8. `retrieval/` — the boundary you sealed yesterday is already leaking

The RAG query layer is some of the best code in this project: four search strategies behind one typed interface, a clean ~20-line weighted Reciprocal Rank Fusion, an answering service whose trace records the *exact prompts* used (want to know why last Tuesday's answer said that? The trace has the full system and user prompt). Several patterns worth keeping:

**Dictionary dispatch beats if/elif chains.** The engine maps an enum to methods — `{RetrievalStrategy.HYBRID: self._hybrid_search, ...}` — and dispatches with a dict lookup. Adding a strategy is one line, and there's no chain to fall through incorrectly.

**Use the database you already have.** The hybrid search's lexical leg isn't an in-memory BM25 library — it's Postgres `ts_rank` full-text search over the chunks table that already exists. No index to rebuild at startup, no extra RAM, one less dependency. Choosing boring infrastructure you already operate over a new component is chronically underrated.

**Make observability part of the return type.** Every search returns a `SearchTrace` (parameters, timing, strategy explanation, trace IDs); every answer an `AnswerTrace` with full prompts. When debugging data comes back *in the response object*, the UI can show it, tests can assert on it, and nobody greps logs to reconstruct what happened.

But the sharpest lesson was archaeological again, and this time about *recency*: this folder was written roughly in parallel with the config work — and it bypasses the config boundary in four places (`os.getenv` for the DB URL, and a whole `LLM_PROVIDER`/`LLM_MODEL` env surface that has no settings group at all). One session ago we sealed exactly this hole in three other files. The conclusion isn't "be more careful" — it's that **boundaries maintained by vigilance decay, and the fix is to encode them mechanically**. Ruff's `flake8-tidy-imports` banned-api rule (TID251) can make `os.getenv` outside `config/` a lint *error*. Ten minutes of configuration outlives any amount of code-review discipline.

Two smaller specimens for the collection: a production attribute that exists *only so a test can assert on it* (`_all_chunks = None  # kept for test assertions`) — when a test needs a hook that production doesn't, the test is asserting internals instead of behavior; and a method named `_bm25_search` that hasn't done BM25 since the FTS rewrite, alongside a `rank-bm25` dependency with zero imports left. Names and dependency lists have inertia; implementations don't. When you swap an implementation, grep for its old name and its old dependency the same day.

One genuinely subtle trap, filed for a fix: `SearchResult.score` means three different things depending on strategy — raw pgvector *distance* for similarity (lower is better!), an RRF score for hybrid (higher is better), nothing for MMR — while the docstring confidently says "higher = more relevant." Every vector-store wrapper has a version of this distance-vs-relevance confusion. If a score field crosses an API boundary, its semantics belong in the type (or at minimum, per-strategy documentation), not in the reader's assumptions.

### 9. Backlog round two — narrow doors, lint-enforced walls, and a database nobody was talking to

Second cleanup batch, and three lessons that only fixing (not reviewing) could have produced.

**Reading one config key shouldn't require validating all of them.** The failure that taught this: a test asked `PDFParser` for its API key and got... a *database* validation error. The parser resolved its key through the composed root — `get_settings().parsing.llamaparse_api_key` — and constructing the root validates every nested group, including `DatabaseSettings`, which demands a DB URL. One component's config read was coupled to the entire application's config being valid. Worse, this had been invisible: the test previously passed only because unrelated test modules happened to set `DATABASE_URL` as an import side effect — a latent test-order dependency that surfaced the moment I ran the file alone. The fix became a policy worth stating: **leaf components construct their narrow settings group directly (`ParsingSettings()`, `LLMSettings()`, `DatabaseSettings()`); only composition roots touch the cached `get_settings()`.** Narrow doors also turn out to be what test-friendliness wants — a fresh group construction sees monkeypatched env vars that a process-lifetime cache would hide.

**A boundary became a lint rule.** Entry 8 predicted that the config boundary would keep re-leaking as long as it was enforced by vigilance. It's now enforced by ruff: `TID251` (banned-api) makes `os.getenv` a lint error everywhere except `config/` (which *is* the boundary) and `scripts/` (entrypoints, temporarily). The satisfying part: by the time the rule went live, the census of violations was already zero — but the rule is the point, because the next `retrieval/`-style folder written in parallel will hit a red CI instead of a review three months later.

**Running migrations on a database Alembic has never met.** The live DB's schema came from `create_all()`, not migrations — so there was no `alembic_version` table, and a naive `alembic upgrade head` would have tried to re-create every existing table. The idiom: `alembic stamp <baseline>` first ("trust me, this revision is already in effect"), *then* `upgrade head` runs only what's new. And the order of operations for adding a unique constraint to live data is a discipline of its own: read-only duplicate check first (zero dupes on `documents.file_path` — the constraint can't fail), then apply, then verify with read-only queries (both indexes present, generated tsvector populated 24/24, the app's actual FTS query returning ranked hits through the GIN index).

And one discovery that no amount of code reading would have found, because it wasn't in the code: **the app's configured `DB_URL` pointed at a database that no longer exists.** Connection refused — the old Supabase instance was decommissioned in the Neon migration, but the `.env` entry was never updated; ingestion kept working only because the batch scripts read a *different* variable (`NEON_DIRECT_URL`). Config drift is invisible precisely because config isn't code: nothing type-checks it, nothing greps it, and the only test is connecting. If your system has two names for "the database," one of them is eventually a lie — worth an occasional `SELECT 1` against every URL you claim to depend on.
