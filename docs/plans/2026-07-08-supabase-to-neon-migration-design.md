# Design: Rescue Supabase Data and Migrate to Neon

**Date**: 2026-07-08
**Status**: Approved — REVISED same day: Management API restore returned "paused more than 90 days,
cannot be restored" (HTTP 400). Recovery path changed to dashboard backup download → restore
directly into Neon. See revised implementation plan.
**Author**: Himanshu (with Claude)

## Problem

The Supabase project (`<project-ref>`, ap-south-1) hosting the meditation
database is **paused** (free-tier auto-pause), and the dashboard restore button
fails with a "status fetch failed" error. The app cannot connect: the pooler
rejects connections with `(ENOTFOUND) tenant/user ... not found`, which is the
signature of a paused project — not a Supabase outage.

The database is the **only copy** of the processed data: no local dumps exist,
and no local Docker volume holds a copy. Re-ingesting from scratch would cost
LlamaParse and Voyage API credits, hours of pipeline time, and — critically —
would mint new chunk UUIDs, invalidating the retrieval eval dataset
(`retrieval/eval_dataset_generation.ipynb` records chunk UUIDs as ground truth)
and making past Langfuse eval runs non-comparable.

## Decision

**Approach A**: Restore the paused project via the Supabase Management API
(bypassing the broken dashboard), take a full local `pg_dump` as insurance,
restore the dump into a new Neon Postgres database, and switch `DB_URL`.

Rejected alternatives:

- **B: Stay on Supabase after restore** — the 7-day auto-pause will recur, and
  the dashboard restore path has proven unreliable; every pause becomes an
  incident. Neon's free tier scales to zero but wakes automatically on
  connection, eliminating the manual-restore failure mode.
- **C: Fresh re-ingestion into Neon** — fallback only. Invalidates the eval
  dataset (new chunk UUIDs), costs API credits and hours. Used only if both the
  Management API restore and Supabase backup download fail.

## Plan

### Step 1 — Restore the paused project via Management API

- User creates a Personal Access Token at
  `supabase.com/dashboard/account/tokens` (manual, user-only step).
- `POST https://api.supabase.com/v1/projects/<project-ref>/restore`
  with `Authorization: Bearer $SUPABASE_PAT`.
- Poll `GET /v1/projects/<project-ref>` until status is
  `ACTIVE_HEALTHY` (typically a few minutes).
- **Fallback**: if the restore call fails, check
  `GET /v1/projects/{ref}/database/backups` for downloadable backups.
  If both fail, escalate to Supabase support; only then consider Approach C.

### Step 2 — Dump everything locally, immediately

- `pg_dump --schema=public --no-owner --no-privileges -Fc` to
  `data/supabase_rescue_<date>.dump` (gitignored).
- Use the **session-mode** connection (port 5432); the transaction pooler on
  6543 does not support `pg_dump`.
- Record row counts of `documents`, `chunks`, `langchain_pg_embedding`, and
  `langchain_pg_collection` for verification in Step 5.

### Step 3 — Prepare Neon and restore

- In the Neon project: `CREATE EXTENSION vector;` (Neon supports pgvector).
- `pg_restore --no-owner --no-privileges` the dump.
- Indexes travel with the dump and are rebuilt on restore, including the
  full-text-search index from the BM25 → Postgres FTS migration.

### Step 4 — Switch application config

- Update `DB_URL` in `.env` to the Neon connection string (use Neon's pooled
  `-pooler` host for the app).
- Keep the old Supabase URL commented in `.env` as a record.
- Sanity-check Supabase-specific pool settings in `db/database.py`; no code
  changes expected.

### Step 5 — Verify

1. Row counts in Neon match the Step-2 numbers exactly.
2. `scripts/verify_database.py` passes.
3. One FTS query and one vector-similarity query return sane results.
4. End-to-end retrieval smoke test on `feature/rag-retrieval-eval` works.
5. `SELECT pg_database_size(current_database())` is under Neon's free-tier
   storage cap (~512MB).

## Error Handling

Every step is non-destructive to the source. Supabase data is never modified
or deleted; any failure means stop and reassess. The Supabase project stays
untouched until Neon is fully verified. The local dump from Step 2 remains as
a permanent offline backup regardless of outcome.

## Known Risks

- **Neon free-tier storage cap (~512MB)**: Supabase free tier is 500MB, so the
  data should fit, but exact size is unknown until after restore. If exceeded,
  decide between Neon paid tier or staying on the restored Supabase.
- **Management API restore may fail**: mitigated by the backup-download
  fallback and, ultimately, Approach C.
