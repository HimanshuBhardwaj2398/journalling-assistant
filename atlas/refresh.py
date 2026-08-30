"""Keep the atlas cache honest about the corpus behind it.

Run after any ingestion:

    poetry run python -m atlas.refresh          # report drift
    poetry run python -m atlas.refresh --rebuild

Every number the atlas reports is computed from the cache, so a cache that
silently lags the database makes the whole analysis quietly wrong.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from atlas.loader import CACHE_DIR, fingerprint, live_uuids, load

logger = logging.getLogger(__name__)


def status(cache_dir: Path = CACHE_DIR, uuids: Optional[Sequence[str]] = None) -> dict:
    """Compare the cached corpus against the live one."""
    uuids = list(uuids) if uuids is not None else live_uuids()
    live = fingerprint(uuids)

    stamp = Path(cache_dir) / "fingerprint.json"
    cached = json.loads(stamp.read_text())["corpus"] if stamp.exists() else None

    return {
        "cached": cached,
        "live": live,
        "cached_chunks": int(cached.split("-", 1)[0]) if cached else None,
        "live_chunks": len(uuids),
        "stale": cached != live,
    }


def rebuild(cache_dir: Path = CACHE_DIR) -> int:
    """Refetch everything and overwrite the cache. Returns the chunk count."""
    vectors, _ = load(refresh=True, cache_dir=cache_dir)
    return len(vectors)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true", help="refetch and overwrite the cache")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    state = status()

    if not state["stale"]:
        print(f"Atlas cache is current — {state['live_chunks']} chunks.")
        return 0

    was = state["cached_chunks"]
    print(
        f"Atlas cache is STALE: cached {was if was is not None else 'nothing'} chunks, "
        f"database has {state['live_chunks']}."
    )
    if not args.rebuild:
        print("Re-run with --rebuild to refetch. Until then every atlas number is out of date.")
        return 1

    print(f"Rebuilding... {rebuild()} chunks cached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
