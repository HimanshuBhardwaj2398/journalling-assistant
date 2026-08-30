"""Markdown comparison tables render strategies × metrics with segments."""

from evals.report import render_comparison, render_markdown

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


def _arm(per_row):
    return {
        "overall": {"mrr": 0.5},
        "by_question_type": {},
        "by_register": {},
        "errors": [],
        "per_row": per_row,
    }


def test_comparison_reports_wins_losses_and_mean_delta():
    results = {
        "dataset_size": 2,
        "strategies": {
            "hybrid+raw": _arm(
                [
                    {"id": "r1", "scores": {"mrr": 0.5}},
                    {"id": "r2", "scores": {"mrr": 0.5}},
                ]
            ),
            "hybrid+model": _arm(
                [
                    {"id": "r1", "scores": {"mrr": 1.0}},
                    {"id": "r2", "scores": {"mrr": 0.5}},
                ]
            ),
        },
    }
    md = render_comparison(results, control="hybrid+raw", metrics=["mrr"])
    assert "hybrid+model" in md
    assert "1W" in md and "0L" in md and "1T" in md
    assert "+0.2500" in md


def test_comparison_omits_the_control_as_its_own_row():
    results = {
        "dataset_size": 1,
        "strategies": {
            "hybrid+raw": _arm([{"id": "r1", "scores": {"mrr": 1.0}}]),
            "hybrid+model": _arm([{"id": "r1", "scores": {"mrr": 1.0}}]),
        },
    }
    md = render_comparison(results, control="hybrid+raw", metrics=["mrr"])
    assert md.count("### hybrid+model") == 1
    assert "### hybrid+raw" not in md


def test_comparison_leads_with_the_fallback_count():
    results = {
        "dataset_size": 1,
        "strategies": {
            "hybrid+raw": _arm([{"id": "r1", "scores": {"mrr": 1.0}}]),
            "hybrid+model": _arm([{"id": "r1", "scores": {"mrr": 1.0}, "fallback": True}]),
        },
    }
    md = render_comparison(results, control="hybrid+raw", metrics=["mrr"])
    assert "1 of 1 rows fell back" in md
    assert "inconclusive" in md


def test_comparison_states_the_sample_size_caveat():
    results = {
        "dataset_size": 23,
        "strategies": {
            "hybrid+raw": _arm([{"id": "r1", "scores": {"mrr": 1.0}}]),
            "hybrid+model": _arm([{"id": "r1", "scores": {"mrr": 1.0}}]),
        },
    }
    md = render_comparison(results, control="hybrid+raw", metrics=["mrr"])
    assert "23 rows" in md
    assert "cannot resolve small" in md


def test_comparison_survives_arms_with_no_shared_rows():
    # One arm erroring every row must degrade to a note, not raise.
    results = {
        "dataset_size": 1,
        "strategies": {
            "hybrid+raw": _arm([{"id": "r1", "scores": {"mrr": 1.0}}]),
            "hybrid+model": _arm([]),
        },
    }
    md = render_comparison(results, control="hybrid+raw", metrics=["mrr"])
    assert "hybrid+model" in md
