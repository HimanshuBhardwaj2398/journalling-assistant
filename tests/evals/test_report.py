"""Markdown comparison tables render strategies × metrics with segments."""

from evals.report import render_markdown

RESULTS = {
    "git_sha": "abc123",
    "dataset_size": 2,
    "k_values": [5],
    "strategies": {
        "hybrid": {
            "overall": {"recall@5": 0.9, "mrr": 0.8},
            "by_register": {"colloquial": {"recall@5": 0.7, "mrr": 0.6}},
            "by_question_type": {},
            "errors": [{"id": "r9", "error": "boom"}],
        },
        "similarity": {
            "overall": {"recall@5": 0.5, "mrr": 0.4},
            "by_register": {"colloquial": {"recall@5": 0.4, "mrr": 0.3}},
            "by_question_type": {},
            "errors": [],
        },
    },
}


def test_render_markdown_tables():
    md = render_markdown(RESULTS)
    assert "| strategy | recall@5 | mrr |" in md
    assert "| hybrid | 0.9 | 0.8 |" in md  # overall table
    assert "### by register: colloquial" in md  # segment table
    assert "1 rows errored" in md  # error surfacing
