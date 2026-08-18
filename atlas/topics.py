"""Name each cluster: distinguishing vocabulary first, then a readable label."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

logger = logging.getLogger(__name__)

# Formulaic scaffolding that appears in nearly every sutta. Pass this as
# `stopwords` for readable labels; leave it out on the first pass, because
# these terms dominating every cluster is itself the pericope finding.
CANON_STOPWORDS = frozenset(
    {
        "mendicant",
        "mendicants",
        "blessed",
        "buddha",
        "sir",
        "reverend",
        "venerable",
        "thus",
        "heard",
        "monastery",
        "dwelling",
        "said",
        "replied",
    }
)

PROMPT = (
    "These are the distinguishing terms and a representative passage from one "
    "cluster of early Buddhist text excerpts.\n\n"
    "Terms: {terms}\n\nPassage:\n{passage}\n\n"
    'Reply with only JSON: {{"name": "<2-4 words>", "gloss": "<one sentence>"}}'
)


def ctfidf_terms(
    texts: Sequence[str],
    labels: np.ndarray,
    top_n: int = 15,
    stopwords: Optional[frozenset] = None,
) -> dict[int, list[str]]:
    """Top distinguishing terms per cluster, treating each cluster as one document."""
    labels = np.asarray(labels)
    ids = sorted(set(labels.tolist()) - {-1})
    documents = [
        " ".join(text for text, label in zip(texts, labels) if label == cluster_id)
        for cluster_id in ids
    ]

    vectorizer = TfidfVectorizer(stop_words=list(ENGLISH_STOP_WORDS | (stopwords or frozenset())))
    matrix = vectorizer.fit_transform(documents).toarray()
    vocabulary = np.array(vectorizer.get_feature_names_out())

    return {
        cluster_id: vocabulary[np.argsort(-row)[:top_n]].tolist()
        for cluster_id, row in zip(ids, matrix)
    }


def label_clusters(
    terms: dict[int, list[str]],
    passages: dict[int, str],
    member_uuids: dict[int, list[str]],
    client=None,
    cache_path: Path = Path("data/atlas/labels.json"),
) -> dict[int, dict]:
    """A name and gloss per cluster, cached so re-runs cost nothing.

    Keyed by the cluster's members, so changing the clustering invalidates only
    the clusters that actually changed.
    """
    cache_path = Path(cache_path)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    if client is None:
        from retrieval.llm_client import LLMClient

        client = LLMClient()

    out = {}
    for cluster_id, words in terms.items():
        key = hashlib.md5(",".join(sorted(member_uuids[cluster_id])).encode()).hexdigest()
        if key not in cache:
            label = _ask(client, words, passages.get(cluster_id, ""))
            if label is None:
                # A model outage is transient; caching the fallback would make it permanent.
                out[cluster_id] = _from_terms(words)
                continue
            cache[key] = label
        out[cluster_id] = cache[key]

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2))
    return out


def _from_terms(words: list[str]) -> dict:
    """Stand-in label built from the cluster's own vocabulary."""
    return {"name": ", ".join(words[:2]), "gloss": ""}


def _ask(client, words: list[str], passage: str) -> Optional[dict]:
    """Label from the model, or None if it could not produce one."""
    prompt = PROMPT.format(terms=", ".join(words), passage=passage[:1500])
    try:
        # Reasoning models spend tokens before the JSON, so leave generous headroom;
        # a truncated reply is unparseable and costs a whole label.
        reply = client.complete([{"role": "user", "content": prompt}], max_tokens=800)
        return json.loads(reply)
    except Exception as error:
        logger.warning("No model label for a cluster, using its terms instead: %s", error)
        return None
