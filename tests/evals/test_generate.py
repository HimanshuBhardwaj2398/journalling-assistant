"""Generation pipeline tests with fake LLM + fake embedder."""

import json

from evals.dataset import Dimensions, EvalRow, Persona, QuestionType, Register
from evals.generate import (
    ChunkSample,
    dedup_rows,
    dimension_deck,
    generate_row,
    parse_json_with_retry,
    run_critics,
)

CHUNK = ChunkSample(
    chunk_uuid="u1",
    document_id=1,
    sutta_uid="mn10",
    nikaya="mn",
    text=(
        "Mindfulness of breathing, when developed, fulfils the four kinds of "
        "mindfulness meditation."
    ),
)
DIMS = Dimensions(
    question_type=QuestionType.PRACTICAL,
    persona=Persona.NEW_MEDITATOR,
    register=Register.COLLOQUIAL,
)


class FakeLLMClient:
    """Returns queued responses; records prompts."""

    model_id = "fake/model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.prompts = []

    def complete(self, messages, temperature=0.0, max_tokens=200):
        self.prompts.append(messages)
        return self.responses.pop(0)


def test_parse_json_retries_once_then_dead_letters():
    ok = json.dumps({"question": "q", "answer": "a"})
    client = FakeLLMClient(["not json", ok])
    assert parse_json_with_retry(client, [{"role": "user", "content": "x"}])["question"] == "q"

    client = FakeLLMClient(["not json", "still not json"])
    assert parse_json_with_retry(client, [{"role": "user", "content": "x"}]) is None


def test_generate_row_builds_valid_eval_row():
    qa = json.dumps({"question": "How do I start breath meditation?", "answer": "Focus on..."})
    client = FakeLLMClient([qa])
    row = generate_row(client, CHUNK, DIMS, row_id="syn_001")
    assert isinstance(row, EvalRow)
    assert row.chunk_uuids == ["u1"] and row.sutta_uids == ["mn10"]
    assert row.origin == "synthetic"
    # dimension instructions made it into the prompt
    prompt_text = client.prompts[0][-1]["content"]
    assert "everyday language" in prompt_text  # colloquial register instruction


def test_run_critics_all_pass_and_one_fail():
    passing = json.dumps({"pass": True, "critique": "fine"})
    failing = json.dumps({"pass": False, "critique": "references the passage"})
    client = FakeLLMClient([passing, passing, passing])
    verdict = run_critics(client, question="q", answer="a", chunk_text="c")
    assert verdict.passed and len(verdict.critiques) == 3

    client = FakeLLMClient([passing, failing, passing])
    assert not run_critics(client, question="q", answer="a", chunk_text="c").passed


def test_dimension_deck_is_deterministic_and_respects_pali_rule():
    deck = dimension_deck(n=50, seed=7)
    assert deck == dimension_deck(n=50, seed=7)
    for dims in deck:
        if dims.question_type == QuestionType.PALI_SPECIFIC:
            assert dims.register == Register.CANONICAL  # pali questions can't be colloquial


def _mk(i, question, vec):
    return (
        EvalRow(
            id=f"syn_{i}",
            question=question,
            sutta_uids=["mn10"],
            chunk_uuids=[f"u{i}"],
            dimensions=DIMS,
            origin="synthetic",
        ),
        vec,
    )


def test_dedup_drops_near_duplicates():
    rows = [
        _mk(1, "How do I start?", [1.0, 0.0]),
        _mk(2, "How do I begin?", [0.999, 0.01]),  # near-dup of row 1
        _mk(3, "What are hindrances?", [0.0, 1.0]),
    ]
    kept = dedup_rows([r for r, _ in rows], embeddings=[v for _, v in rows], threshold=0.95)
    assert [r.id for r in kept] == ["syn_1", "syn_3"]
