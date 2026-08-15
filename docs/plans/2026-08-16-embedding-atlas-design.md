# Design: Embedding Atlas — Mapping the Distribution of the Corpus

**Date**: 2026-08-16
**Status**: Approved
**Author**: Himanshu (with Claude)
**Branch**: `feature/embedding-atlas`
**Scope**: Exploratory analysis of the chunk embedding space — distribution
diagnostics, a 2D map with clusters and centroids, topic labels, and pericope
(near-duplicate) structure. **Insight-first.** This design ships no change to
retrieval. Anything it suggests for retrieval enters the eval-gated ladder from
the [retrieval eval strategy design](2026-07-13-retrieval-eval-strategy-design.md)
as a separate piece of work.

---

## 1. Context

997 chunks from 156 documents (152 MN, 4 DN) are embedded with `voyage-3.5` into
1024 dimensions, stored in the `buddhist_texts` collection of
`langchain_pg_embedding` and linked to `chunks` by UUID. Four retrieval
strategies read that space; nobody has yet looked at its *shape*.

The question this answers: what does the corpus look like as a distribution, and
what does that tell us about why retrieval behaves as it does?

Decisions made in brainstorming (2026-08-16):

| Question | Decision |
|---|---|
| Primary goal | **Insight and visualization** — understanding the texts and a shareable map, not a retrieval change. |
| Corpus scope | **Ingest DN fully first** (30 missing suttas) → 186 docs, est. 1.5–1.8k chunks. Gives DN's long doctrinal discourses to contrast against MN. |
| Deliverable | **Notebook-first**, driven by a thin importable module. |
| Analyses | All four: distribution diagnostics, the map, topic labels, pericope structure. |
| Code style | **Simple, readable, small.** Plain numpy/pandas/dict returns; no custom result classes; no framework. |

### Facts established by inspecting the live database

These shaped the design and are recorded because several contradict reasonable
assumptions:

- **All embeddings have L2 norm exactly 1.0.** Voyage returns normalized
  vectors. A norm histogram and any length-vs-norm correlation are therefore
  degenerate — they were dropped from the diagnostics and replaced with
  cosine-geometry measures.
- **Two collections exist**: `buddhist_texts` (997 rows) and `meditation_chunks`
  (0 rows, vestigial). Queries must filter by collection name.
- **`chunk_index` is absent from `cmetadata`**, so the join to `chunks` is
  required. `document` holds the chunk text and is never null. The join
  `cmetadata->>'uuid' = chunks.uuid` covers 997/997 rows.
- **MN 10 (Satipaṭṭhāna) and DN 22 (Mahāsatipaṭṭhāna) are near-identical texts**
  — DN 22 is MN 10 with the Four Noble Truths section expanded. Once DN is
  ingested this gives the map a free correctness check.

## 2. Corpus drift — a pre-existing problem this design must not step over

`data/evals/corpus_manifest_v1.json` (frozen 2026-07-15) records 20 documents
and 124 chunks. The live database holds **156 documents and 997 chunks**. The
corpus grew roughly eightfold and the manifest never registered it.

`evals/corpus.py::verify_manifest` was built to detect exactly this, but it only
fires when something calls it, and the corpus grew without anything doing so.
The consequence: the single eval result on disk
(`data/evals/results/e9e7595-20260715T201935.json`) was measured against a
retrieval pool that no longer exists.

This is not caused by the atlas, but the DN ingestion adds ~600 more chunks and
makes it worse. Scope stays narrow — fixing the eval harness is separate work:

- After DN ingestion, re-freeze as `corpus_manifest_v2.json`.
- Record that pre-v2 eval results are non-comparable.
- The atlas records which manifest version it was computed against, so a map and
  an eval run can be aligned later.

## 3. Layout

`experiments/` is gitignored, so a notebook there would stay local. The atlas is
meant to be shareable, so it becomes a tracked top-level package alongside
`evals/` and `retrieval/`:

```
atlas/
  loader.py      load + disk-cache vectors and metadata from Neon
  geometry.py    distribution diagnostics
  structure.py   UMAP projection + HDBSCAN clusters + centroids/exemplars
  topics.py      c-TF-IDF terms + LLM labels
  pericopes.py   near-duplicate mining
  atlas.ipynb    the narrative; imports the above, holds all plotting
data/atlas/      cached vectors, cluster assignments, cached labels
```

One module per analysis, plus the loader. Plotting lives in the notebook rather
than a `plots.py`, so each chart reads next to the figure it produces.

Tracking the notebook means its outputs appear in diffs. `retrieval/*.ipynb` are
already tracked, so this matches existing practice; `nbstripout` as a pre-commit
hook is the fix if the noise becomes annoying.

## 4. Components

### loader.py

One query, filtered by the collection name from `VectorSettings`, joined to
`chunks` for `chunk_index`. Returns `X: np.ndarray[n, 1024] float32` and a
`pd.DataFrame` of metadata (uuid, chunk_text, sutta_uid, nikaya, doc_title,
chunk_index, word_count).

Cached to `data/atlas/` — about 7 MB at this size — with a fingerprint of row
count plus md5 of sorted UUIDs. A mismatch warns loudly rather than silently
serving stale vectors, which is the failure mode §2 describes.

### geometry.py — distribution diagnostics

Every measure here exploits the unit-sphere fact from §1.

- **Anisotropy**: mean pairwise cosine (computed exactly — n² is trivial at this
  size) against the ≈0 an isotropic space would produce, plus `‖mean(X)‖`. If
  that norm is high, most of every vector is one shared direction, and
  similarity scores have far less dynamic range than they appear to.
- **Cosine distributions**: four overlaid histograms — within-sutta,
  within-nikāya, cross-nikāya, random pairs. The gap between within-sutta and
  random is the real signal-to-noise of the space.
- **PCA curve**: dimensions needed for 50/90/95% variance, and whether PC1
  correlates with `word_count` (a known embedding artifact).
- **Hubness**: k-occurrence skew at k=10 plus the top hub chunks — the ones that
  turn up in every neighborhood regardless of query.

### structure.py — the map

UMAP with `metric='cosine'`, `min_dist=0.1`, `random_state=42`. Below ~2000
points UMAP is genuinely sensitive to `n_neighbors`, so the notebook renders
5 / 15 / 30 side by side rather than picking one and trusting it.

Clustering runs **HDBSCAN on the full 1024 dimensions, not on the 2D
projection** — clustering the projection is a standard and serious mistake, as
UMAP distorts density by construction. `sklearn.cluster.HDBSCAN` (built into
scikit-learn ≥1.3, so no extra dependency) with `metric='euclidean'`, which is
exact rather than approximate here: on unit-norm vectors
‖a−b‖² = 2 − 2·cos(a,b), so euclidean ordering is identical to cosine ordering.

`min_cluster_size` is swept over {10, 15, 25} with noise fraction reported. If
noise exceeds roughly 40%, the honest conclusion is that the corpus is a
continuum rather than a set of clusters — that is a result, not a failure.

Centroid = renormalized mean of members. Exemplar = the member closest to the
centroid, which gives each region a readable representative passage.

### topics.py — labels

c-TF-IDF over cluster pseudo-documents (each cluster's chunks concatenated,
TF-IDF across clusters).

The first pass deliberately keeps all words. "Mendicants", "Blessed One" and
"thus have I heard" swamping every cluster *is* the pericope finding, and
stripping it early would hide the most interesting property of the corpus. A
second pass with a domain stoplist produces the readable labels.

Labels come from the existing multi-provider `retrieval/llm_client.py`: top-15
c-TF-IDF terms plus three exemplar chunks in, a name and one-line gloss out.
Cached by md5 of member UUIDs, so re-runs are free and changed clusters
invalidate correctly.

### pericopes.py — near-duplicate structure

A dense cosine matrix (1800² float32 ≈ 13 MB, so exact beats approximate
nearest-neighbor here), with self-pairs and same-sutta-adjacent pairs masked.
Threshold sweep over {0.85, 0.90, 0.95}; connected components of the thresholded
graph are pericope families. The headline number is the share of the corpus
sitting inside a near-duplicate family.

The MN 10 ↔ DN 22 check aligns each DN 22 chunk to its best-matching MN 10 chunk.
A strong diagonal confirms the map reflects textual reality; its absence means
the projection is not to be trusted.

## 5. Data flow

```
Neon (langchain_pg_embedding ⋈ chunks, filtered by collection)
  → loader (cached to data/atlas/ with fingerprint)
  → geometry / structure / pericopes  (pure functions over X, df)
  → topics (c-TF-IDF → LLM labels, cached)
  → notebook: plotly figures + artifacts written back to data/atlas/
```

## 6. Error handling

Failures degrade rather than crashing mid-notebook:

- Database errors raise from the `MeditationDBError` hierarchy in
  `core/exceptions.py`, per project convention.
- A cache fingerprint mismatch warns and refuses to silently serve stale data.
- An empty collection is caught explicitly — the `meditation_chunks` trap.
- A failed LLM label falls back to the c-TF-IDF top terms.
- An all-noise HDBSCAN result is reported as a finding, not an exception.

## 7. Testing

Tests use synthetic vectors with planted structure, consistent with the
project's practice of faking external services:

| Target | Test |
|---|---|
| `geometry` | A cone of known mean cosine recovers that anisotropy; an orthonormal set gives ≈0. |
| `structure` | Gaussian blobs on the sphere recover the planted cluster count; exemplar is nearest the true center. |
| `pericopes` | Planted exact and near duplicates group into the expected families. |
| `topics` | c-TF-IDF on a toy corpus surfaces the known distinguishing terms. |
| `loader` | The row → `(X, df)` transform against a fixed fake payload. No network. |

UMAP layout and LLM label text are not asserted on — there is no meaningful
assertion to make about either.

## 8. Dependencies

`umap-learn` and `plotly`. Nothing else: numpy, pandas and scikit-learn already
arrive transitively via `sentence-transformers` and `streamlit`, and HDBSCAN
ships inside scikit-learn.

BERTopic was considered and rejected. It is largely UMAP + HDBSCAN + c-TF-IDF
behind one interface, its defaults assume corpora an order of magnitude larger,
it clusters on reduced dimensions by default (§4), and the diagnostics and
pericope analysis would sit outside it regardless.

## 9. Out of scope

- **Writing tags into `chunk_metadata`.** Tempting once clusters have labels, but
  tags that shape retrieval must first beat the incumbent on Recall@5 and MRR
  through the eval gate. That is separate work.
- **Retrieval changes of any kind.** This design produces hypotheses, not
  defaults.
- **Fixing the eval harness drift** beyond re-freezing the manifest (§2).
- **SN / AN / KN ingestion.** ~4000 further suttas would make this a genuine map
  of the Canon; it is a later decision, taken once DN+MN shows the approach
  yields something worth scaling.
