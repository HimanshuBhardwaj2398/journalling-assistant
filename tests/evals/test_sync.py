"""Langfuse dataset sync: rows map to item specs; upsert goes through the tracer port."""

from config.settings import LangfuseSettings
from evals.dataset import Dimensions, EvalRow, Persona, QuestionType, Register
from evals.sync import sync_rows, to_item_spec
from observability.langfuse import LangfuseTracer


def _row(row_id="seed_001", **overrides):
    base = dict(
        id=row_id,
        question="Why am I restless in meditation?",
        reference_answer=None,
        sutta_uids=["sn46.2"],
        chunk_uuids=[],
        source_document_ids=[],
        dimensions=Dimensions(
            question_type=QuestionType.PRACTICAL,
            persona=Persona.NEW_MEDITATOR,
            register=Register.COLLOQUIAL,
        ),
        origin="manual",
        model_version=None,
    )
    base.update(overrides)
    return EvalRow(**base)


class FakeClient:
    def __init__(self):
        self.datasets = []
        self.items = []

    def create_dataset(self, *, name, description=None, **kwargs):
        self.datasets.append((name, description))

    def create_dataset_item(self, **kwargs):
        self.items.append(kwargs)


def test_to_item_spec_maps_fields():
    spec = to_item_spec(_row())
    assert spec.id == "seed_001"
    assert spec.input == {"question": "Why am I restless in meditation?"}
    assert spec.expected_output["sutta_uids"] == ["sn46.2"]
    assert spec.metadata["register"] == "colloquial"
    assert spec.metadata["origin"] == "manual"


def test_sync_rows_upserts_by_row_id():
    client = FakeClient()
    tracer = LangfuseTracer(client=client)
    count = sync_rows(tracer, [_row(), _row(row_id="seed_002")], name="retrieval-eval-v1")
    assert count == 2
    assert client.datasets[0][0] == "retrieval-eval-v1"
    assert [item["id"] for item in client.items] == ["seed_001", "seed_002"]
    assert all(item["dataset_name"] == "retrieval-eval-v1" for item in client.items)


def test_sync_rows_disabled_tracer_returns_none():
    tracer = LangfuseTracer(
        client=None,
        settings=LangfuseSettings(public_key=None, secret_key=None),
    )
    assert sync_rows(tracer, [_row()], name="retrieval-eval-v1") is None


def test_sync_rows_survives_item_failure():
    class FlakyClient(FakeClient):
        def create_dataset_item(self, **kwargs):
            if kwargs["id"] == "seed_001":
                raise RuntimeError("api hiccup")
            super().create_dataset_item(**kwargs)

    tracer = LangfuseTracer(client=FlakyClient())
    count = sync_rows(tracer, [_row(), _row(row_id="seed_002")], name="ds")
    assert count == 1  # failed item logged, not fatal
