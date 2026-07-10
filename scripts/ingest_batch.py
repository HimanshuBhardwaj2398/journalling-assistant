#!/usr/bin/env python3
"""Batch-ingest SuttaCentral suttas into Neon (skips already-ingested sources).

Composition root: points the app DB + vector store at NEON_DIRECT_URL via the
injectable Database, ensures schema, then ingests each source through the
pipeline. Sources already present (by file_path) are skipped to avoid duplicates.

Usage:
    poetry run python scripts/ingest_batch.py                          # mn1..mn5
    poetry run python scripts/ingest_batch.py sc:mn1/sujato sc:dn1/sujato
"""

import asyncio
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env")

from config.settings import DatabaseSettings, get_settings  # noqa: E402
from db.crud import DocumentCRUD  # noqa: E402
from db.database import Database, session_scope, set_default_database  # noqa: E402
from ingestion.embed import VectorStoreConfig  # noqa: E402
from ingestion.orchestrator import IngestionOrchestrator  # noqa: E402


def _default_sources() -> list[str]:
    return [f"sc:mn{i}/sujato" for i in range(1, 6)]


async def _ingest_all(sources: list[str], collection: str, neon_url: str) -> None:
    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(collection_name=collection, db_url=neon_url)
    )
    for source in sources:
        with session_scope() as session:
            if DocumentCRUD(session).check_duplicate(source):
                print(f"skip (already ingested): {source}")
                continue
        result = await orchestrator.process(source)
        print(
            f"ingested {source}: doc={result['document_id']} "
            f"chunks={result['chunk_count']} success={result['success']}"
        )


def main(argv: list[str]) -> None:
    sources = argv or _default_sources()
    neon_url = os.getenv("NEON_DIRECT_URL")
    if not neon_url:
        raise SystemExit("NEON_DIRECT_URL is not set in the environment/.env")

    database = Database(DatabaseSettings(url=neon_url))
    set_default_database(database)
    database.init_db()

    collection = get_settings().vector.collection_name
    print(f"Batch-ingesting {len(sources)} source(s) into {collection!r} ...")
    asyncio.run(_ingest_all(sources, collection, neon_url))


if __name__ == "__main__":
    main(sys.argv[1:])
