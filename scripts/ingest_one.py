#!/usr/bin/env python3
"""Ingest a single SuttaCentral text into Neon — the end-to-end proof.

Composition root: points the application database (used by ``session_scope`` in
the pipeline) and the vector store at ``NEON_DIRECT_URL`` via the injectable
``Database``, ensures the schema exists, then runs the ingestion pipeline
(parse -> chunk -> embed -> persist).

Usage:
    poetry run python scripts/ingest_one.py                        # sc:mn1/sujato -> default collection
    poetry run python scripts/ingest_one.py sc:dn1/sujato
    poetry run python scripts/ingest_one.py sc:dn1/sujato talks    # route to another collection
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
from db.database import Database, set_default_database  # noqa: E402
from ingestion.embed import VectorStoreConfig  # noqa: E402
from ingestion.orchestrator import IngestionOrchestrator  # noqa: E402


def main(argv: list[str]) -> None:
    source = argv[0] if argv else "sc:mn1/sujato"
    collection = argv[1] if len(argv) > 1 else get_settings().vector.collection_name

    neon_url = os.getenv("NEON_DIRECT_URL")
    if not neon_url:
        raise SystemExit("NEON_DIRECT_URL is not set in the environment/.env")

    # Point the module-level session_scope (used by the pipeline) at Neon DIRECT.
    database = Database(DatabaseSettings(url=neon_url))
    set_default_database(database)

    print("Ensuring schema on Neon (pgvector extension + tables) ...")
    database.init_db()

    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(collection_name=collection, db_url=neon_url)
    )

    print(f"Ingesting {source!r} into collection {collection!r} ...")
    result = asyncio.run(orchestrator.process(source))

    print("\n=== Ingestion result ===")
    print(f"document_id : {result['document_id']}")
    print(f"title       : {result['title']}")
    print(f"chunk_count : {result['chunk_count']}")
    print(f"success     : {result['success']}")
    print(f"stages      : {result['stage_results']}")
    if result.get("errors"):
        print(f"errors      : {result['errors']}")


if __name__ == "__main__":
    main(sys.argv[1:])
