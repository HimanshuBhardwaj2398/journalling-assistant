"""Render eval results as markdown comparison tables (Strategy × Metric)."""

from __future__ import annotations


def _table(metric_names: list[str], rows: dict[str, dict[str, float]]) -> str:
    header = "| strategy | " + " | ".join(metric_names) + " |"
    sep = "|" + "---|" * (len(metric_names) + 1)
    lines = [header, sep]
    for strategy, metrics in rows.items():
        cells = " | ".join(str(metrics.get(m, "—")) for m in metric_names)
        lines.append(f"| {strategy} | {cells} |")
    return "\n".join(lines)


def render_markdown(results: dict) -> str:
    strategies = results["strategies"]
    first = next(iter(strategies.values()))
    metric_names = list(first["overall"].keys())

    parts = [
        f"## Retrieval eval — {results.get('git_sha', '?')} "
        f"({results.get('dataset_size', '?')} rows)",
        "\n### overall\n",
        _table(metric_names, {s: d["overall"] for s, d in strategies.items()}),
    ]

    for segment_key in ("by_register", "by_question_type"):
        segment_values = sorted({v for d in strategies.values() for v in d[segment_key]})
        for value in segment_values:
            parts.append(f"\n### {segment_key.replace('_', ' ')}: {value}\n")
            parts.append(
                _table(
                    metric_names,
                    {s: d[segment_key].get(value, {}) for s, d in strategies.items()},
                )
            )

    error_count = sum(len(d["errors"]) for d in strategies.values())
    if error_count:
        parts.append(f"\n⚠️ {error_count} rows errored — see results JSON for details.")
    return "\n".join(parts)


def render_comparison(results: dict, *, control: str, metrics: list[str]) -> str:
    """Render each arm against the control: mean delta, paired 95% CI, W/L/T.

    Leads with the sample size and each arm's fallback count on purpose. At 23
    rows a reader who takes a delta at face value will over-read it, and an arm
    whose interpreter kept falling back to the raw question *is* the control on
    those rows — a tie there means "the interpreter never ran", not "rewriting
    does not help".
    """
    from evals.stats import bootstrap_ci, paired_deltas

    arms = results["strategies"]
    size = results.get("dataset_size", "?")

    def scores_for(arm_name: str, metric: str) -> dict[str, float]:
        return {
            r["id"]: r["scores"][metric] for r in arms[arm_name]["per_row"] if metric in r["scores"]
        }

    parts = [
        f"## Arm comparison vs `{control}` — {size} rows",
        "",
        f"> Sample size is {size} rows. This run can support "
        "'no measurable difference' or 'a large difference'; it "
        "cannot resolve small ones.",
        "",
    ]

    for arm_name, arm in arms.items():
        if arm_name == control:
            continue
        rows = arm["per_row"]
        fallbacks = sum(1 for r in rows if r.get("fallback"))
        parts.append(f"### {arm_name}")
        parts.append("")
        if fallbacks:
            parts.append(
                f"⚠️ **{fallbacks} of {len(rows)} rows fell back to the raw question** — "
                "on those rows this arm *is* the control, so a null result here is "
                "inconclusive rather than a tie. Check the recorded `intent` to tell a "
                "dead parse from a row classified `other`."
            )
            parts.append("")
        parts.append("| metric | mean Δ | 95% CI (paired) | W/L/T |")
        parts.append("|---|---|---|---|")
        for metric in metrics:
            try:
                delta = paired_deltas(scores_for(arm_name, metric), scores_for(control, metric))
                lo, hi = bootstrap_ci(delta["deltas"])
            except ValueError as exc:
                parts.append(f"| {metric} | — | {exc} | — |")
                continue
            wlt = f"{delta['wins']}W / {delta['losses']}L / {delta['ties']}T"
            parts.append(
                f"| {metric} | {delta['mean_delta']:+.4f} | [{lo:+.4f}, {hi:+.4f}] | {wlt} |"
            )
        parts.append("")

    return "\n".join(parts)
