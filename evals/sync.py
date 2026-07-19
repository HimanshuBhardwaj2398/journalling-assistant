"""Sync the local eval dataset to a Langfuse hosted dataset.

The JSONL in git stays the source of truth; the hosted copy powers the Langfuse
datasets UI (retriever-comparison runs). Items upsert by row id, so re-syncing
after edits is safe and idempotent.

CLI (requires LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY):
    poetry run python -m evals.sync --dataset data/evals/retrieval_v1.jsonl \
        --name retrieval-eval-v1
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from evals.dataset import EvalRow
from observability.langfuse import DatasetItemSpec, LangfuseTracer

logger = logging.getLogger(__name__)


def to_item_spec(row: EvalRow) -> DatasetItemSpec:
    """Map an eval row to a hosted dataset item (display copy; truth stays local)."""
    return DatasetItemSpec(
        id=row.id,
        input={"question": row.question},
        expected_output={
            "reference_answer": row.reference_answer,
            "sutta_uids": row.sutta_uids,
            "chunk_uuids": row.chunk_uuids,
            "source_document_ids": row.source_document_ids,
        },
        metadata={
            "question_type": row.dimensions.question_type.value,
            "persona": row.dimensions.persona.value,
            "register": row.dimensions.register.value,
            "origin": row.origin,
            "model_version": row.model_version,
        },
    )


def sync_rows(
    tracer: LangfuseTracer,
    rows: Sequence[EvalRow],
    *,
    name: str,
    description: Optional[str] = None,
) -> Optional[int]:
    """Push rows to the hosted dataset. Returns items synced, None when Langfuse is off."""
    return tracer.sync_dataset(
        name=name,
        description=description,
        items=[to_item_spec(row) for row in rows],
    )


def main() -> None:  # pragma: no cover - thin CLI; components tested above
    import argparse

    from evals.dataset import load_dataset
    from observability.langfuse import get_langfuse_tracer

    parser = argparse.ArgumentParser(description="Sync the eval dataset to Langfuse")
    parser.add_argument("--dataset", default="data/evals/retrieval_v1.jsonl")
    parser.add_argument("--name", default="retrieval-eval-v1")
    parser.add_argument(
        "--description",
        default="Retrieval eval dataset (source of truth: data/evals/*.jsonl in git)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rows = load_dataset(args.dataset)
    synced = sync_rows(get_langfuse_tracer(), rows, name=args.name, description=args.description)
    if synced is None:
        raise SystemExit("Langfuse is not configured (LANGFUSE_PUBLIC_KEY/SECRET_KEY)")
    print(f"Synced {synced}/{len(rows)} items -> Langfuse dataset '{args.name}'")


if __name__ == "__main__":
    main()
