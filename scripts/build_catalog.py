#!/usr/bin/env python3
"""Build the SuttaCentral catalog of early Buddhist texts.

Enumerates every sutta translated by the chosen author/language from the
bilara-data GitHub tree and writes one JSON object per line to
``data/suttacentral_catalog.jsonl`` — the reusable list of "all links".

Usage:
    poetry run python scripts/build_catalog.py                # all nikayas (dn mn sn an kn)
    poetry run python scripts/build_catalog.py dn mn          # selected nikayas
"""

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from ingestion.suttacentral import SuttaCentralCatalog  # noqa: E402

_DEFAULT_NIKAYAS = ("dn", "mn", "sn", "an", "kn")
_OUTPUT_PATH = _PROJECT_ROOT / "data" / "suttacentral_catalog.jsonl"


def main(argv: list[str]) -> None:
    nikayas = tuple(argv) if argv else _DEFAULT_NIKAYAS
    print(f"Crawling bilara-data for nikayas: {', '.join(nikayas)} ...")

    entries = SuttaCentralCatalog().crawl(nikayas=nikayas)

    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _OUTPUT_PATH.open("w") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")

    per_nikaya: dict[str, int] = {}
    for entry in entries:
        per_nikaya[entry["nikaya"]] = per_nikaya.get(entry["nikaya"], 0) + 1
    summary = ", ".join(f"{nikaya}={count}" for nikaya, count in sorted(per_nikaya.items()))
    print(f"Wrote {len(entries)} entries ({summary}) to {_OUTPUT_PATH}")


if __name__ == "__main__":
    main(sys.argv[1:])
