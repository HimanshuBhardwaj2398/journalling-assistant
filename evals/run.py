"""Eval runner: scores every registered retrieval strategy against a dataset.

Truth resolution per row (first non-empty wins):
  1. chunk_uuids -> chunk-level scoring against SearchResult.chunk_uuid
  2. source_document_ids (or sutta_uids resolved via the corpus manifest)
     -> document-level scoring against SearchResult.document_id

Ground truth is always read from the local rows (looked up by item id), never
from the Langfuse-hosted copy. When Langfuse is configured, each strategy runs
as a dataset experiment (one dataset run per strategy, per-row metrics as
scores); offline, an identical local loop shares the same scoring functions.
The results JSON is written either way and stays the source of truth.

CLI (requires DATABASE_URL + VOYAGE_API_KEY; Langfuse keys optional):
    poetry run python -m evals.run --dataset data/evals/retrieval_v1.jsonl \
        --manifest data/evals/corpus_manifest_v1.json
"""

from __future__ import annotations

import json
import logging
import statistics
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from evals.dataset import EvalRow
from evals.metrics import hit_rate_at_k, mrr, ndcg_at_k, recall_at_k

logger = logging.getLogger(__name__)


@dataclass
class StrategyReport:
    strategy: str
    overall: dict[str, float] = field(default_factory=dict)
    by_question_type: dict[str, dict[str, float]] = field(default_factory=dict)
    by_register: dict[str, dict[str, float]] = field(default_factory=dict)
    per_row: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def serialize_results(results) -> list[dict]:
    """SearchResults -> JSON-serializable rows (also the traced experiment output)."""
    return [
        {
            "rank": r.rank,
            "chunk_uuid": r.chunk_uuid,
            "document_id": r.document_id,
            "source_title": r.source_title,
            "score": r.score,
        }
        for r in results
    ]


def score_output(row: EvalRow, retrieved: list[dict], k_values: list[int]) -> dict[str, float]:
    """Score one row's serialized retrieval output against its local ground truth."""
    if row.chunk_uuids:
        relevant = set(row.chunk_uuids)
        ids = [str(r["chunk_uuid"]) for r in retrieved]
    else:
        relevant = {str(d) for d in row.source_document_ids}
        ids = [str(r["document_id"]) for r in retrieved]

    # Doc-level scoring maps many chunks to one document; keep first occurrence
    # only, else repeated hits inflate DCG past the ideal (NDCG > 1).
    ids = list(dict.fromkeys(ids))

    scores: dict[str, float] = {"mrr": mrr(relevant, ids)}
    for k in k_values:
        scores[f"recall@{k}"] = recall_at_k(relevant, ids, k)
        scores[f"ndcg@{k}"] = ndcg_at_k(relevant, ids, k)
        scores[f"hit_rate@{k}"] = hit_rate_at_k(relevant, ids, k)
    return scores


def _aggregate(rows: list[dict]) -> dict[str, float]:
    if not rows:
        return {}
    keys = rows[0]["scores"].keys()
    return {k: round(statistics.mean(r["scores"][k] for r in rows), 4) for k in keys}


def _finalize(report: StrategyReport) -> StrategyReport:
    report.overall = _aggregate(report.per_row)
    for dim_key, bucket in (
        ("question_type", report.by_question_type),
        ("register", report.by_register),
    ):
        for value in sorted({r[dim_key] for r in report.per_row}):
            bucket[value] = _aggregate([r for r in report.per_row if r[dim_key] == value])
    return report


def _per_row_entry(row: EvalRow, scores: dict[str, float]) -> dict:
    return {
        "id": row.id,
        "question_type": row.dimensions.question_type.value,
        "register": row.dimensions.register.value,
        "scores": scores,
    }


def evaluate_strategy(retriever, rows: list[EvalRow], k_values: list[int]) -> StrategyReport:
    """Offline scoring loop — same serialize/score functions as the Langfuse path."""
    report = StrategyReport(strategy=retriever.name)
    for row in rows:
        try:
            retrieved = serialize_results(retriever.retrieve(row.question, k=max(k_values)))
            report.per_row.append(_per_row_entry(row, score_output(row, retrieved, k_values)))
        except Exception as exc:  # per-row failures are data, not crashes
            logger.warning("row %s failed on %s: %s", row.id, retriever.name, exc)
            report.errors.append({"id": row.id, "error": str(exc)})
    return _finalize(report)


def run_strategy_with_langfuse(
    tracer,
    retriever,
    rows: list[EvalRow],
    *,
    k_values: list[int],
    dataset_name: str,
    run_name: str,
    metadata: Optional[dict[str, str]] = None,
) -> Optional[StrategyReport]:
    """Run one strategy as a Langfuse dataset experiment. None when Langfuse is off.

    Every hosted item becomes a trace scored with the same functions the offline
    loop uses; local rows missing from the outcomes are reported as errors.
    """
    rows_by_id = {row.id: row for row in rows}

    def task(item_id: str, item_input) -> dict:
        row = rows_by_id.get(item_id)
        question = row.question if row else (item_input or {}).get("question", "")
        return {"retrieved": serialize_results(retriever.retrieve(question, k=max(k_values)))}

    def scorer(item_id: str, output: dict) -> dict[str, float]:
        row = rows_by_id.get(item_id)
        if row is None:  # hosted item unknown locally — no ground truth, no scores
            return {}
        return score_output(row, output["retrieved"], k_values)

    outcomes = tracer.run_dataset_experiment(
        dataset_name=dataset_name,
        run_name=run_name,
        task=task,
        scorer=scorer,
        metadata=metadata,
    )
    if outcomes is None:
        return None

    report = StrategyReport(strategy=retriever.name)
    seen: set[str] = set()
    for outcome in outcomes:
        row = rows_by_id.get(outcome.item_id)
        if row is None:
            logger.warning("hosted item %s has no local row; skipping", outcome.item_id)
            continue
        seen.add(outcome.item_id)
        if outcome.scores:
            report.per_row.append(_per_row_entry(row, outcome.scores))
        else:
            report.errors.append({"id": row.id, "error": "experiment produced no scores"})
    for row in rows:
        if row.id not in seen:
            report.errors.append(
                {"id": row.id, "error": "no experiment outcome (item not synced or task failed)"}
            )
    return _finalize(report)


def resolve_sutta_anchors(rows: list[EvalRow], uid_to_doc_ids: dict[str, list[int]]) -> None:
    """Fill source_document_ids for rows anchored only by sutta uid (mutates rows)."""
    for row in rows:
        if not row.chunk_uuids and not row.source_document_ids:
            resolved = [d for uid in row.sutta_uids for d in uid_to_doc_ids.get(uid, [])]
            row.source_document_ids = resolved
            if not resolved:
                logger.warning("row %s: no documents found for suttas %s", row.id, row.sutta_uids)


def main() -> None:  # pragma: no cover - thin CLI; components tested above
    import argparse

    from db.database import session_scope
    from evals.corpus import CorpusManifest, verify_manifest
    from evals.dataset import load_dataset
    from evals.report import render_markdown
    from observability.langfuse import get_langfuse_tracer
    from retrieval.registry import default_retrievers

    parser = argparse.ArgumentParser(description="Run retrieval evals for all strategies")
    parser.add_argument("--dataset", default="data/evals/retrieval_v1.jsonl")
    parser.add_argument("--manifest", default="data/evals/corpus_manifest_v1.json")
    parser.add_argument("--k", type=int, nargs="+", default=[5, 10])
    parser.add_argument("--out-dir", default="data/evals/results")
    parser.add_argument("--allow-drift", action="store_true")
    parser.add_argument("--langfuse-dataset", default="retrieval-eval-v1")
    parser.add_argument("--no-langfuse", action="store_true", help="force the offline loop")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    manifest = CorpusManifest.load(args.manifest)
    with session_scope() as session:
        problems = verify_manifest(session, manifest)
    if problems:
        for p in problems:
            logger.error("corpus drift: %s", p)
        if not args.allow_drift:
            raise SystemExit("corpus drifted from manifest; regenerate dataset or --allow-drift")

    rows = load_dataset(args.dataset)
    resolve_sutta_anchors(rows, manifest.uid_to_document_ids())
    rows = [r for r in rows if r.chunk_uuids or r.source_document_ids]

    git_sha = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    tracer = None if args.no_langfuse else get_langfuse_tracer()

    results = {
        "git_sha": git_sha,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": args.dataset,
        "dataset_size": len(rows),
        "k_values": args.k,
        "strategies": {},
    }
    for name, retriever in default_retrievers().items():
        logger.info("evaluating strategy: %s", name)
        report = None
        if tracer is not None:
            report = run_strategy_with_langfuse(
                tracer,
                retriever,
                rows,
                k_values=args.k,
                dataset_name=args.langfuse_dataset,
                run_name=f"{name}-{git_sha or 'nogit'}-{stamp}",
                metadata={"strategy": name, "git_sha": git_sha},
            )
        if report is None:
            report = evaluate_strategy(retriever, rows, k_values=args.k)
        results["strategies"][name] = {
            "overall": report.overall,
            "by_question_type": report.by_question_type,
            "by_register": report.by_register,
            "errors": report.errors,
            "per_row": report.per_row,
        }

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{git_sha or 'nogit'}-{stamp}.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(render_markdown(results))
    print(f"\nresults written to {out_path}")


if __name__ == "__main__":
    main()
