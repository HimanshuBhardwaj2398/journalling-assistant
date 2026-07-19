# Design: SuttaCentral Catalog + HTML Ingestion (via injected DB)

**Date**: 2026-07-10
**Status**: Proposed — awaiting approval
**Author**: Himanshu (with Claude)
**Depends on**: [Architecture Hardening & Retrieval Foundations](2026-07-10-architecture-hardening-retrieval-foundations-design.md) (decision D1: injectable `Database`)

---

## 1. Goal & scope

Build a reusable **catalog of all early Buddhist texts** on SuttaCentral, then **ingest one sutta
end-to-end** as a proof — reading the **HTML version** (best structure for our header-aware chunker),
writing into **Neon**, through an **inverted (injected) database dependency**.

**Decisions locked in (from brainstorming):**

| Decision | Choice | Why |
|---|---|---|
| Source | **Official SuttaCentral API** | Robust, official, preserves canonical UIDs for citations/eval |
| Text form | **Reconstructed HTML** from bilara layers | Best structure (headings/verse); modern full coverage (Sujato) |
| First pass | **Catalog all + ingest one** | Small, safe, verifiable proof |
| Target DB | **Neon** (DIRECT url) | Real target; DIRECT endpoint suits a batch job under SQLAlchemy's own pool |

**Non-goals (YAGNI):** not ingesting the whole corpus yet; not scraping the SPA with a headless
browser; not re-embedding or GraphRAG; not building the full repository layer (only the DB-inversion
slice ingestion needs).

---

## 2. SuttaCentral API — verified findings

Researched firsthand against the live API (endpoints confirmed, see §11 sources).

### 2.1 Enumeration — the "all links" catalog

`GET /api/menu` returns a **hierarchical tree** of collections with recursive `children`:

- Roots: `sutta`, `vinaya`, `abhidhamma` (+ standalone texts).
- `sutta` → branches: Long (`dn`), Middle (`mn`), Linked (`sn`), Numbered (`an`), Minor (`kn`), Other.
- Each node: `{ uid, children, node_type, root_lang_iso, ... }`; `node_type` ∈ {root, branch, leaf}.
- Chinese/Sanskrit/Tibetan/Gāndhārī branches are included → we can scope to "early texts" by branch.

**Catalog crawl:** start at `/api/menu`, recursively expand nodes (`/api/menu/{uid}` for children)
until leaf sutta UIDs, recording `{ uid, top_collection, language, reading_url, has_segmented,
author_uid }`. Persist as the catalog. (Exact child-expansion pagination verified during build.)

### 2.2 Two text forms — the key distinction

`GET /api/suttas/{uid}/{author}?lang=en` returns a `segmented` boolean:

- **Legacy** (`segmented: false`, e.g. Bhikkhu Bodhi): the `translation` field contains **monolithic
  HTML** directly. `markdownify` it as-is.
- **Segmented / bilara** (`segmented: true`, e.g. **Bhikkhu Sujato** — the modern, complete set):
  **no inline HTML**; the `/api/suttas` response is metadata only. Text lives in the bilara endpoint.

### 2.3 Reconstructing HTML for segmented texts (the "HTML version" we want)

`GET /api/bilarasuttas/{uid}/{author}?lang=en` returns parallel layers keyed by segment ID:

| Key | Contents (example, `mn1`) |
|---|---|
| `html_text` | `"mn1:0.1": "<article id='mn1'><header><ul><li class='division'>{}</li></ul>"`, `"mn1:3.1": "<p data-counter='1'>{}"`, `"mn1:26.5": "<p class='endsection'>{}</p>"` |
| `translation_text` | `"mn1:3.1": "Take an unlearned ordinary person who has not seen…"` |
| `root_text` | `"mn1:3.1": "Idha, bhikkhave, assutavā puthujjano…"` (Pali) |
| `keys_order` | ordered list of all segment IDs |

**Reconstruction algorithm** (deterministic — produces the same HTML the site renders client-side):

```python
def bilara_to_html(bilara: dict, *, use: str = "translation_text") -> str:
    html_parts = []
    for seg_id in bilara["keys_order"]:
        template = bilara["html_text"].get(seg_id, "{}")   # structure, or bare placeholder
        text = bilara[use].get(seg_id, "")                 # english (or root_text for Pali)
        html_parts.append(template.replace("{}", text))
    return "".join(html_parts)
```

`<article>/<header>/<h1>/<p>` → `markdownify` → clean `#`/`##` header-delimited markdown, i.e. exactly
what `MarkdownChunker` splits on. Verse/quotes preserved via block tags.

### 2.4 Resulting ingestion rule per sutta

```
segmented == true  → bilara endpoint → reconstruct HTML → markdownify
segmented == false → /api/suttas legacy `translation` HTML → markdownify
```

Every ingested document keeps its **canonical UID** (e.g. `mn1`) + `author_uid` in metadata — durable
identity for citations and the retrieval-eval ground truth.

---

## 3. Architecture

Reuses the existing Strategy-pattern parsing + chunking + embedding + orchestrator. **Two new pieces**
(a source parser and a catalog crawler) and **one refactor** (inject the DB).

```
/api/menu ──► SuttaCentralCatalog ──► catalog rows {uid, author, url, segmented, collection}
   (crawl)         (new)                        │
                                                ▼  (pick ONE for the proof)
                       SuttaCentralParser (new, implements Parser protocol)
                          │  fetch bilara/legacy → reconstruct HTML → markdown
                          ▼
   existing:  MarkdownChunker ─► VectorStoreManager(embed) ─► DB persistence (chunks/documents)
                                                                      │
                                            injected Database  ───────┘  ──►  NEON (DIRECT url)
```

### 3.1 New: `SuttaCentralParser` (fits `ParserFactory`)

Implements the existing `Parser` protocol ([core/interfaces.py:36](../../core/interfaces.py#L36)):

- `can_parse(source)` → true for `suttacentral.net/...` reading URLs **or** a `sc:{uid}/{author}`
  shorthand. (Registered in `ParserFactory` *before* the generic `URLParser`, so SC URLs route here.)
- `parse(source)` → resolve `{uid, author}` → `GET /api/suttas/{uid}/{author}` to read `segmented` →
  bilara-reconstruct or legacy-HTML → `markdownify` → `ParseResult(content, title, metadata={uid,
  author_uid, source_url, segmented, source:"suttacentral"})`.
- Polite HTTP: shared `requests.Session`, timeout, retry/backoff, `User-Agent`, small delay between
  calls, on-disk response cache (avoid re-hitting the API during dev).

### 3.2 New: `SuttaCentralCatalog`

- `crawl(collections=("dn","mn","sn","an","kn"))` → recursively expand `/api/menu` → list of catalog
  entries. Persisted to `data/suttacentral_catalog.jsonl` (v1 — a file, not a DB table; YAGNI).
- Pure functions for tree-walk are unit-testable against a fixture menu JSON.

### 3.3 Refactor: invert the DB dependency (architecture doc D1, scoped)

Only the slice ingestion needs:

- `db/database.py`: introduce `Database(settings)` owning the engine + `session_scope`; **remove the
  import-time global engine** (kills the `os.environ.setdefault` test hack).
- Ingestion path (`orchestrator` / persistence stage / `ingestion_service`) accepts an injected
  `Database` (or session factory) instead of importing the module-level `session_scope`.
- **Neon wiring**: `DatabaseSettings.url` resolves from `NEON_DIRECT_URL` for ingestion (SQLAlchemy
  manages its own pool; DIRECT avoids PgBouncer prepared-statement issues); the Streamlit app can use
  `NEON_POOLER_URL`. Both already in `.env`; `DB_URL` is currently stale (dead Supabase).

---

## 4. Data flow — the "ingest one" proof

1. `SuttaCentralCatalog.crawl()` → write `data/suttacentral_catalog.jsonl` (all early-text UIDs).
2. Pick one proof sutta — **`mn1` (Mūlapariyāya) / sujato** (segmented → exercises the bilara→HTML
   path, the harder/more valuable case).
3. Construct `Database(settings)` → `init_db()` on Neon (creates `vector` extension + tables — **with
   explicit go-ahead**, since Neon is empty after the data loss).
4. `orchestrator.process("sc:mn1/sujato", database=db, collection_name=settings.vector.collection_name)`
   → parse (SC parser) → chunk → embed (Voyage) → persist (injected DB).
5. **Verify**: `documents` has 1 row (uid `mn1`); `chunks` count > 0; `langchain_pg_embedding` count ==
   chunks; a similarity search for a phrase from MN1 returns the chunk.

---

## 5. Error handling & politeness

- **Network**: retry with backoff on 5xx / timeouts; fail the single doc (don't abort a batch) and log,
  consistent with existing pipeline behavior.
- **Rate limiting**: serial fetch + small delay; on-disk cache keyed by endpoint URL. The catalog crawl
  hits `/api/menu*` only (small); text endpoints are fetched lazily, one per ingested sutta.
- **Missing data**: segment in `html_text` but not `translation_text` → substitute empty (structural
  segment). No English translation for a UID → skip with a logged reason (record in catalog).
- **Idempotency**: reuse existing duplicate check on `file_path`/source; re-ingest replaces via the
  reprocess path.

---

## 6. Testing (TDD)

- `bilara_to_html` — pure function; unit-test with a small fixture bilara dict → asserts substitution +
  ordering + missing-segment handling. **No network.**
- Catalog tree-walk — pure function over a fixture `/api/menu` node → asserts leaf UID collection.
- `SuttaCentralParser.parse` — inject a fake HTTP client returning fixture JSON → asserts `ParseResult`
  markdown has headers + correct metadata. **No network.**
- DB inversion — the injected `Database` enables an ingestion test against a throwaway/local DB; unit
  tests use fakes (per architecture doc §9). Removes the import-time env hack.
- One **integration** test (marked `slow`, opt-in): real API fetch of `mn1` → markdown sanity checks.

---

## 7. Components / files

```
ingestion/
  suttacentral.py     # NEW  SuttaCentralParser + bilara_to_html + SuttaCentralCatalog
  parsing.py          # MODIFIED  register SuttaCentralParser in ParserFactory (before URLParser)
db/
  database.py         # MODIFIED  Database(settings); no import-time engine (D1 slice)
config/settings.py    # MODIFIED  VectorSettings.collection_name; url resolves NEON_DIRECT_URL
services/ingestion_service.py  # MODIFIED  pass injected Database into orchestrator
scripts/
  build_catalog.py    # NEW  CLI: crawl menu → data/suttacentral_catalog.jsonl
  ingest_one.py       # NEW  CLI: ingest a single uid/author into Neon (the proof)
data/suttacentral_catalog.jsonl  # NEW  persisted catalog
tests/ingestion/test_suttacentral.py  # NEW
```

---

## 8. Phased plan (for the implementation plan)

- **Phase A — SuttaCentral source (no DB):** `bilara_to_html`, `SuttaCentralParser`, catalog crawl +
  `build_catalog.py`. Fully TDD-able offline with fixtures.
- **Phase B — Invert DB + wire Neon:** `Database` object, remove import-time engine, resolve
  `NEON_DIRECT_URL`, `init_db()` on Neon (with go-ahead).
- **Phase C — Ingest one + verify:** `ingest_one.py` for `mn1/sujato` → Neon; run the §4 verification.

Order honors your ask: **catalog → invert DB → ingest one.**

---

## 9. Risks & open questions

- **R1 — menu child expansion**: exact endpoint/pagination to drill from branch → leaf UIDs verified in
  Phase A (fallback: the `suttacentral/bilara-data` GitHub tree, which lists every UID).
- **R2 — heading levels**: confirm the reconstructed HTML's `<h1>/<h2>` map to the chunker's expected
  header depth; adjust `markdownify` heading style if needed.
- **R3 — Neon empty**: `init_db()` is safe/idempotent but connects + writes to Neon → **needs your
  explicit go-ahead** before Phase C.
- **R4 — DB-inversion blast radius**: many `session_scope` call sites. Phase B keeps a
  backward-compatible module-level `session_scope` (delegating to a lazily-built default `Database`) so
  we don't touch every call site at once — import-time side effect still removed.
- **R5 — Pali vs English**: v1 ingests English (`translation_text`). Bilingual (root+translation
  interleaved) is a later option; the reconstruction already supports `root_text`.

---

## 10. What I need from you to proceed past Phase B

- **Go-ahead to run `init_db()` against Neon** (creates extension + tables in the empty DB).
- Confirm the proof sutta (**default `mn1`/sujato**) — or name another.

---

## 11. Sources (verified during research)

- SuttaCentral API docs (Swagger): https://suttacentral.net/api/docs/
- Get Sutta Information and Legacy translations API (dev forum):
  https://discourse.suttacentral.net/t/get-sutta-information-and-legacy-translations-api/25942
- Get SuttaPlex data API (dev forum): https://discourse.suttacentral.net/t/get-suttaplex-data-api/30038
- SuttaCentral app source: https://github.com/suttacentral/suttacentral
- `suttacentral-api` (npm, community client): https://www.npmjs.com/package/suttacentral-api
