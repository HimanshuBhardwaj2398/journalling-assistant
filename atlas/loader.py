"""Load chunk embeddings and metadata from Postgres, cached to disk.

pgvector renders a vector as ``[0.1,-0.2,...]`` over a raw query, which arrives
as a str and happens to be valid JSON — so json.loads is the whole parser.

Reads go through the shared ``session_scope`` rather than a private engine, so
the atlas inherits the application pool (pre-ping and keepalives — Neon drops
idle connections) and follows ``set_default_database`` like every other caller.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import text

from config.settings import VectorSettings
from core.exceptions import CollectionError
from db.database import session_scope

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/atlas")

COLUMNS = [
    "uuid",
    "chunk_text",
    "embedding",
    "sutta_uid",
    "nikaya",
    "doc_title",
    "word_count",
    "chunk_index",
]

QUERY = text(
    """
    SELECT e.cmetadata->>'uuid'              AS uuid,
           e.document                        AS chunk_text,
           e.embedding::text                 AS embedding,
           e.cmetadata->>'uid'               AS sutta_uid,
           e.cmetadata->>'nikaya'            AS nikaya,
           e.cmetadata->>'doc_title'         AS doc_title,
           (e.cmetadata->>'word_count')::int AS word_count,
           c.chunk_index                     AS chunk_index
      FROM langchain_pg_embedding e
      JOIN langchain_pg_collection col ON col.uuid = e.collection_id
      JOIN chunks c ON c.uuid = e.cmetadata->>'uuid'
     WHERE col.name = :collection
     ORDER BY e.cmetadata->>'uuid'
    """
)

UUIDS_QUERY = text(
    """
    SELECT e.cmetadata->>'uuid'
      FROM langchain_pg_embedding e
      JOIN langchain_pg_collection col ON col.uuid = e.collection_id
     WHERE col.name = :collection
    """
)


def fingerprint(uuids: Iterable[str]) -> str:
    """Stable id for a corpus snapshot: row count plus md5 of the sorted uuids."""
    uuids = sorted(uuids)
    return f"{len(uuids)}-{hashlib.md5(','.join(uuids).encode()).hexdigest()}"


def rows_to_frame(rows: Sequence[Sequence[Any]]) -> tuple[np.ndarray, pd.DataFrame]:
    """Split query rows into a (n, dim) matrix and a metadata frame."""
    if not rows:
        raise CollectionError(
            "No embeddings found for this collection. Check VECTOR_COLLECTION_NAME — "
            "'meditation_chunks' exists but is empty; the data is in 'buddhist_texts'."
        )
    df = pd.DataFrame(rows, columns=COLUMNS)
    vectors = np.array([json.loads(v) for v in df.pop("embedding")], dtype=np.float32)
    return vectors, df


def fetch() -> tuple[np.ndarray, pd.DataFrame]:
    """Read the configured collection straight from Postgres."""
    collection = VectorSettings().collection_name
    with session_scope() as session:
        rows = session.execute(QUERY, {"collection": collection}).fetchall()
    logger.info("Loaded %d chunks from collection %s", len(rows), collection)
    return rows_to_frame(rows)


def load(refresh: bool = False, cache_dir: Path = CACHE_DIR) -> tuple[np.ndarray, pd.DataFrame]:
    """Vectors and metadata, served from the cache unless refresh is asked for."""
    vectors_path = cache_dir / "vectors.npy"
    meta_path = cache_dir / "meta.parquet"

    if not refresh and vectors_path.exists() and meta_path.exists():
        return np.load(vectors_path), pd.read_parquet(meta_path)

    vectors, df = fetch()
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(vectors_path, vectors)
    df.to_parquet(meta_path)
    (cache_dir / "fingerprint.json").write_text(json.dumps({"corpus": fingerprint(df["uuid"])}))
    return vectors, df


def live_uuids() -> list[str]:
    """Chunk uuids currently in the configured collection. Cheap: ids only."""
    collection = VectorSettings().collection_name
    with session_scope() as session:
        return list(session.execute(UUIDS_QUERY, {"collection": collection}).scalars().all())


def check_drift(cache_dir: Path = CACHE_DIR) -> bool:
    """True when the cache still matches the database."""
    stamp = cache_dir / "fingerprint.json"
    if not stamp.exists():
        return True

    cached = json.loads(stamp.read_text())["corpus"]
    live = fingerprint(live_uuids())
    if cached == live:
        return True
    logger.warning("Atlas cache is stale (%s -> %s). Call load(refresh=True).", cached, live)
    return False
