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
