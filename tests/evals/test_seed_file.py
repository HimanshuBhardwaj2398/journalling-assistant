"""The committed seed file must always validate against the dataset schema."""

from evals.dataset import load_dataset


def test_manual_seed_file_is_valid():
    rows = load_dataset("data/evals/manual_seed.jsonl")
    assert len(rows) >= 3
    for row in rows:
        assert row.origin == "manual"
        assert row.sutta_uids, f"{row.id}: manual rows anchor on sutta uids"
