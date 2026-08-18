"""Topic tests: distinguishing terms, and labels that degrade instead of crashing."""

import numpy as np

from atlas.topics import CANON_STOPWORDS, ctfidf_terms, label_clusters


class FakeClient:
    def __init__(self, reply='{"name": "Jhana", "gloss": "meditative absorption"}'):
        self.reply = reply
        self.calls = 0

    def complete(self, messages, **kw):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_ctfidf_surfaces_each_cluster_distinguishing_terms():
    texts = [
        "jhana absorption rapture",
        "jhana absorption bliss",
        "monastery robes almsfood",
        "monastery robes bowl",
    ]
    labels = np.array([0, 0, 1, 1])

    terms = ctfidf_terms(texts, labels, top_n=3)

    assert "jhana" in terms[0]
    assert "monastery" in terms[1]
    assert "jhana" not in terms[1]


def test_ctfidf_ignores_noise_chunks():
    texts = ["jhana absorption", "monastery robes", "unrelated noise text"]
    labels = np.array([0, 1, -1])

    assert set(ctfidf_terms(texts, labels)) == {0, 1}


def test_canon_stopwords_drop_the_formulaic_scaffolding():
    texts = ["mendicants the blessed one taught jhana", "mendicants the blessed one taught alms"]
    labels = np.array([0, 1])

    terms = ctfidf_terms(texts, labels, stopwords=CANON_STOPWORDS)

    assert "mendicants" not in terms[0] + terms[1]
    assert "jhana" in terms[0]


def test_label_clusters_asks_once_and_then_uses_the_cache(tmp_path):
    client = FakeClient()
    cache = tmp_path / "labels.json"
    terms = {0: ["jhana", "absorption"]}
    uuids = {0: ["a", "b"]}

    first = label_clusters(terms, {0: "text"}, uuids, client=client, cache_path=cache)
    second = label_clusters(terms, {0: "text"}, uuids, client=client, cache_path=cache)

    assert first[0]["name"] == "Jhana"
    assert first == second
    assert client.calls == 1


def test_changing_a_cluster_membership_invalidates_its_label(tmp_path):
    client = FakeClient()
    cache = tmp_path / "labels.json"
    terms = {0: ["jhana"]}

    label_clusters(terms, {0: "t"}, {0: ["a"]}, client=client, cache_path=cache)
    label_clusters(terms, {0: "t"}, {0: ["a", "b"]}, client=client, cache_path=cache)

    assert client.calls == 2


def test_label_falls_back_to_terms_when_the_model_fails(tmp_path):
    client = FakeClient(reply=RuntimeError("provider down"))

    labels = label_clusters(
        {0: ["jhana", "absorption"]},
        {0: "text"},
        {0: ["a"]},
        client=client,
        cache_path=tmp_path / "labels.json",
    )

    assert labels[0]["name"] == "jhana, absorption"
