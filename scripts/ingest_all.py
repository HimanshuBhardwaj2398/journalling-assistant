#!/usr/bin/env python3
"""Parallel bulk-ingest of the remaining SuttaCentral catalog into Neon.

Shards the catalog across worker processes. The pipeline is dominated by
network round-trip latency (Neon status writes, SuttaCentral fetch, Voyage
embedding) rather than CPU, so sharding across processes scales close to
linearly.

Resumability is keyed on DocumentStatus.COMPLETED, not on row existence:
``DocumentCRUD.check_duplicate`` matches on file_path alone, so a document
that failed mid-pipeline would otherwise be skipped forever. Incomplete rows
are reprocessed in full instead.

Usage:
    poetry run python scripts/ingest_all.py                    # all remaining
    poetry run python scripts/ingest_all.py --workers 4
    poetry run python scripts/ingest_all.py --limit 20         # smoke test
    poetry run python scripts/ingest_all.py --dry-run
"""

import argparse
import asyncio
import json
import multiprocessing as mp
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env")

CATALOG = _PROJECT_ROOT / "data" / "suttacentral_catalog.jsonl"

# Kept out of the default worklist: narrative birth-tales (Jataka) and the
# verse biography (Cariyapitaka) sit further from the discourse corpus.
EXCLUDED_KN_PREFIXES = {"ja", "cp"}

MAX_ATTEMPTS = 3
# SuttaCentral answers some requests in >20s and 502s under strain, so back off
# generously rather than hammering an upstream that is already struggling.
RETRY_BACKOFF_SECONDS = (10, 45)


def _lookup_document_id(source: str) -> Optional[int]:
    """Return the document id for ``source``, if a row already exists."""
    from db.database import session_scope
    from db.schema import Document

    with session_scope() as session:
        row = session.query(Document.id).filter(Document.file_path == source).first()
        return int(row[0]) if row else None


def _uid_prefix(uid: str) -> str:
    match = re.match(r"([a-z]+)", uid)
    return match.group(1) if match else ""


def load_catalog(include_all_kn: bool = False) -> List[str]:
    """Return `sc:` source strings for every catalogued sutta we want ingested."""
    sources: List[str] = []
    with CATALOG.open() as handle:
        for line in handle:
            entry = json.loads(line)
            nikaya = entry["nikaya"]
            if nikaya == "kn" and not include_all_kn:
                if _uid_prefix(entry["uid"]) in EXCLUDED_KN_PREFIXES:
                    continue
            sources.append(f"sc:{entry['uid']}/{entry['author']}")
    return sources


def partition_worklist(sources: List[str]) -> Tuple[List[str], List[Tuple[str, int]]]:
    """Split catalog sources into (fresh, incomplete) against current DB state.

    Returns sources never seen before, and (source, document_id) pairs for rows
    that exist but never reached COMPLETED.
    """
    from db.database import session_scope
    from db.schema import Document, DocumentStatus

    with session_scope() as session:
        rows = session.query(Document.file_path, Document.id, Document.status).all()

    completed = {r[0] for r in rows if r[2] == DocumentStatus.COMPLETED}
    incomplete = {r[0]: r[1] for r in rows if r[2] != DocumentStatus.COMPLETED}

    fresh = [s for s in sources if s not in completed and s not in incomplete]
    stale = [(s, incomplete[s]) for s in sources if s in incomplete]
    return fresh, stale


def _build_orchestrator(neon_url: str):
    """Create a worker-local Database + orchestrator.

    Pools are deliberately small: worker_count * (pool_size + max_overflow)
    is the ceiling on concurrent Neon connections.
    """
    from config.settings import DatabaseSettings, get_settings
    from db.database import Database, set_default_database
    from ingestion.embed import VectorStoreConfig
    from ingestion.orchestrator import IngestionOrchestrator

    database = Database(DatabaseSettings(url=neon_url, pool_size=2, max_overflow=3))
    set_default_database(database)

    collection = get_settings().vector.collection_name
    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(collection_name=collection, db_url=neon_url)
    )
    return orchestrator


async def _run_shard(
    worker_id: int,
    shard: List[Tuple[str, Optional[int]]],
    neon_url: str,
    progress: Any,
) -> Dict[str, Any]:
    orchestrator = _build_orchestrator(neon_url)

    ingested = 0
    chunks = 0
    failures: List[Dict[str, str]] = []

    for source, existing_id in shard:
        last_error = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                # A failed attempt still leaves the document row it created, so
                # re-running process(source) would collide on the unique
                # file_path index and the retry could never succeed. Re-resolve
                # the id each attempt and reprocess in place instead.
                if existing_id is None and attempt > 1:
                    existing_id = _lookup_document_id(source)

                if existing_id is not None:
                    result = await orchestrator.process(existing_id, reprocess_mode="full")
                else:
                    result = await orchestrator.process(source)

                if not result.get("success"):
                    raise RuntimeError(
                        "; ".join(result.get("errors") or ["pipeline reported failure"])
                    )

                ingested += 1
                chunks += result.get("chunk_count") or 0
                break
            except Exception as exc:  # keep the shard alive; record and move on
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
        else:
            failures.append({"source": source, "error": last_error})

        with progress.get_lock():
            progress.value += 1

    return {
        "worker_id": worker_id,
        "ingested": ingested,
        "chunks": chunks,
        "failures": failures,
    }


def _worker_entry(
    worker_id: int,
    shard: List[Tuple[str, Optional[int]]],
    neon_url: str,
    progress: Any,
    results: Any,
) -> None:
    import logging

    from config.logging_config import setup_logging

    setup_logging()
    # Per-document stage chatter would interleave across 8 processes.
    logging.getLogger().setLevel(logging.WARNING)

    try:
        results[worker_id] = asyncio.run(_run_shard(worker_id, shard, neon_url, progress))
    except Exception as exc:
        results[worker_id] = {
            "worker_id": worker_id,
            "ingested": 0,
            "chunks": 0,
            "failures": [{"source": "<worker>", "error": f"{type(exc).__name__}: {exc}"}],
        }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=8, help="worker processes (default 8)")
    parser.add_argument("--limit", type=int, default=None, help="cap the worklist (smoke tests)")
    parser.add_argument("--dry-run", action="store_true", help="report the worklist and exit")
    parser.add_argument(
        "--include-all-kn",
        action="store_true",
        help=f"also ingest KN prefixes excluded by default: {sorted(EXCLUDED_KN_PREFIXES)}",
    )
    args = parser.parse_args(argv)

    neon_url = os.getenv("NEON_DIRECT_URL")
    if not neon_url:
        raise SystemExit("NEON_DIRECT_URL is not set in the environment/.env")

    from config.settings import DatabaseSettings
    from db.database import Database, set_default_database

    database = Database(DatabaseSettings(url=neon_url))
    set_default_database(database)
    database.init_db()

    sources = load_catalog(include_all_kn=args.include_all_kn)
    fresh, stale = partition_worklist(sources)

    worklist: List[Tuple[str, Optional[int]]] = [(s, None) for s in fresh]
    worklist += [(s, doc_id) for s, doc_id in stale]

    if args.limit is not None:
        worklist = worklist[: args.limit]

    print(f"catalog considered : {len(sources)}")
    print(f"already completed  : {len(sources) - len(fresh) - len(stale)}")
    print(f"fresh to ingest    : {len(fresh)}")
    print(f"incomplete to redo : {len(stale)}")
    print(f"worklist           : {len(worklist)}")

    if args.dry_run or not worklist:
        if not worklist:
            print("nothing to do.")
        return

    worker_count = max(1, min(args.workers, len(worklist)))
    shards: List[List[Tuple[str, Optional[int]]]] = [[] for _ in range(worker_count)]
    for index, item in enumerate(worklist):
        shards[index % worker_count].append(item)

    print(f"workers            : {worker_count}")
    print(f"shard sizes        : {[len(s) for s in shards]}")
    print("-" * 60, flush=True)

    ctx = mp.get_context("spawn")
    progress = ctx.Value("i", 0)
    manager = ctx.Manager()
    results = manager.dict()

    started = time.time()
    processes = [
        ctx.Process(
            target=_worker_entry,
            args=(worker_id, shards[worker_id], neon_url, progress, results),
        )
        for worker_id in range(worker_count)
    ]
    for process in processes:
        process.start()

    total = len(worklist)
    while any(p.is_alive() for p in processes):
        time.sleep(15)
        done = progress.value
        elapsed = time.time() - started
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        print(
            f"[{elapsed / 60:6.1f}m] {done:5d}/{total} "
            f"({100 * done / total:5.1f}%)  {rate * 60:5.1f}/min  eta {eta / 60:6.1f}m",
            flush=True,
        )

    for process in processes:
        process.join()

    ingested = sum(r["ingested"] for r in results.values())
    chunks = sum(r["chunks"] for r in results.values())
    failures = [f for r in results.values() for f in r["failures"]]

    elapsed = time.time() - started
    print("-" * 60)
    print(f"elapsed   : {elapsed / 60:.1f} min")
    print(f"ingested  : {ingested}/{total}")
    print(f"chunks    : {chunks}")
    print(f"failures  : {len(failures)}")

    if failures:
        failure_log = _PROJECT_ROOT / "data" / "ingest_failures.json"
        failure_log.write_text(json.dumps(failures, indent=2))
        print(f"failure detail -> {failure_log}")
        for failure in failures[:10]:
            print(f"  {failure['source']}: {failure['error'][:120]}")


if __name__ == "__main__":
    main()
