"""Runner scores strategies against a dataset using fake retrievers."""

from evals.dataset import Dimensions, EvalRow, Persona, QuestionType, Register
from evals.run import evaluate_strategy, merge_multi_query, run_strategy_with_langfuse
from retrieval.query import SearchResult


def _row(row_id, chunk_uuids=None, doc_ids=None, register=Register.CANONICAL):
    return EvalRow(
        id=row_id,
        question="q",
        sutta_uids=["mn10"],
        chunk_uuids=chunk_uuids or [],
        source_document_ids=doc_ids or [],
        dimensions=Dimensions(
            question_type=QuestionType.FACTUAL,
            persona=Persona.SCHOLAR,
            register=register,
        ),
        origin="manual",
    )


class FakeRetriever:
    name = "fake"

    def __init__(self, results):
        self._results = results

    def retrieve(self, query, k=5):
        return self._results[:k]


def _res(uuid, doc_id, rank):
    return SearchResult(text="t", chunk_uuid=uuid, document_id=doc_id, rank=rank)


def test_chunk_level_scoring():
    retriever = FakeRetriever([_res("u1", 1, 1), _res("u2", 2, 2)])
    report = evaluate_strategy(retriever, [_row("r1", chunk_uuids=["u2"])], k_values=[1, 2])
    assert report.overall["recall@2"] == 1.0
    assert report.overall["recall@1"] == 0.0
    assert report.overall["mrr"] == 0.5


def test_doc_level_fallback_when_no_chunk_truth():
    retriever = FakeRetriever([_res("u1", 7, 1)])
    report = evaluate_strategy(retriever, [_row("r1", doc_ids=[7])], k_values=[1])
    assert report.overall["recall@1"] == 1.0


def test_doc_level_duplicates_do_not_inflate_ndcg():
    # three chunks of the same document occupy ranks 1-3; the doc counts once
    retriever = FakeRetriever([_res("u1", 7, 1), _res("u2", 7, 2), _res("u3", 7, 3)])
    report = evaluate_strategy(retriever, [_row("r1", doc_ids=[7])], k_values=[3])
    assert report.overall["ndcg@3"] == 1.0
    assert report.overall["recall@3"] == 1.0


def test_segments_and_errors_are_reported():
    class Exploding:
        name = "boom"

        def retrieve(self, query, k=5):
            raise RuntimeError("db down")

    rows = [_row("r1", chunk_uuids=["u1"], register=Register.COLLOQUIAL)]
    report = evaluate_strategy(Exploding(), rows, k_values=[5])
    assert report.errors and "db down" in report.errors[0]["error"]

    retriever = FakeRetriever([_res("u1", 1, 1)])
    report = evaluate_strategy(retriever, rows, k_values=[5])
    assert report.by_register["colloquial"]["recall@5"] == 1.0


class FakeExperimentTracer:
    """Simulates the tracer port: runs task+scorer over hosted item ids."""

    def __init__(self, hosted_item_ids):
        self._hosted = hosted_item_ids
        self.calls = []

    def run_dataset_experiment(self, *, dataset_name, run_name, task, scorer, **kwargs):
        from observability.langfuse import ExperimentItemOutcome

        self.calls.append((dataset_name, run_name))
        outcomes = []
        for item_id in self._hosted:
            output = task(item_id, {"question": "q"})
            outcomes.append(
                ExperimentItemOutcome(
                    item_id=item_id,
                    output=output,
                    scores=scorer(item_id, output),
                    trace_id=f"trace-{item_id}",
                )
            )
        return outcomes


class DisabledTracer:
    def run_dataset_experiment(self, **kwargs):
        return None


def test_langfuse_path_matches_offline_scores():
    rows = [_row("r1", chunk_uuids=["u2"]), _row("r2", chunk_uuids=["u1"])]
    retriever = FakeRetriever([_res("u1", 1, 1), _res("u2", 2, 2)])
    tracer = FakeExperimentTracer(hosted_item_ids=["r1", "r2"])

    offline = evaluate_strategy(retriever, rows, k_values=[2])
    hosted = run_strategy_with_langfuse(
        tracer, retriever, rows, k_values=[2], dataset_name="ds", run_name="fake-abc"
    )
    assert hosted is not None
    assert hosted.overall == offline.overall
    assert tracer.calls == [("ds", "fake-abc")]


def test_langfuse_path_reports_missing_hosted_items_as_errors():
    rows = [_row("r1", chunk_uuids=["u1"]), _row("r2", chunk_uuids=["u1"])]
    retriever = FakeRetriever([_res("u1", 1, 1)])
    tracer = FakeExperimentTracer(hosted_item_ids=["r1"])  # r2 never synced

    report = run_strategy_with_langfuse(
        tracer, retriever, rows, k_values=[1], dataset_name="ds", run_name="run"
    )
    assert [e["id"] for e in report.errors] == ["r2"]
    assert [r["id"] for r in report.per_row] == ["r1"]


def test_langfuse_path_returns_none_when_disabled():
    rows = [_row("r1", chunk_uuids=["u1"])]
    retriever = FakeRetriever([_res("u1", 1, 1)])
    report = run_strategy_with_langfuse(
        DisabledTracer(), retriever, rows, k_values=[1], dataset_name="ds", run_name="run"
    )
    assert report is None


def test_merge_preserves_first_query_order():
    per_query = [[_res("u1", 1, 1), _res("u2", 2, 2)], [_res("u3", 3, 1)]]
    merged = merge_multi_query(per_query, cap=10)
    assert [r.chunk_uuid for r in merged] == ["u1", "u2", "u3"]


def test_merge_dedups_across_queries():
    per_query = [[_res("u1", 1, 1)], [_res("u1", 1, 1), _res("u2", 2, 2)]]
    merged = merge_multi_query(per_query, cap=10)
    assert [r.chunk_uuid for r in merged] == ["u1", "u2"]


def test_merge_caps_total_length():
    per_query = [[_res(f"u{i}", i, i) for i in range(5)], [_res("u9", 9, 1)]]
    merged = merge_multi_query(per_query, cap=3)
    assert len(merged) == 3


def test_merge_renumbers_ranks():
    per_query = [[_res("u1", 1, 7)], [_res("u2", 2, 3)]]
    merged = merge_multi_query(per_query, cap=10)
    assert [r.rank for r in merged] == [1, 2]


def test_merge_falls_back_to_text_when_uuid_missing():
    a = SearchResult(text="same", chunk_uuid=None, document_id=1, rank=1)
    b = SearchResult(text="same", chunk_uuid=None, document_id=1, rank=1)
    assert len(merge_multi_query([[a], [b]], cap=10)) == 1


def test_merge_handles_no_queries():
    assert merge_multi_query([], cap=5) == []


def test_merge_does_not_mutate_the_callers_results():
    # Renumbering is the eval's own addition, not something retrieve_node does.
    # A retriever that returns cached or shared objects (FakeRetriever does)
    # would otherwise leak one arm's ranks into the next arm's audit output.
    original = _res("u1", 1, 7)
    merge_multi_query([[original]], cap=10)
    assert original.rank == 7
