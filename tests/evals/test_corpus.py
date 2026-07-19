"""Manifest build/verify against a fake session."""

from evals.corpus import CorpusManifest, build_manifest, verify_manifest

ROWS = [
    # (document_id, title, sutta_uid, chunk_count, chunk_uuid_md5)
    (1, "MN 10: Satipatthana", "mn10", 12, "aaa"),
    (2, "MN 118: Anapanassati", "mn118", 8, "bbb"),
]


class FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *_args, **_kwargs):
        class R:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        return R(self._rows)


def test_build_manifest():
    m = build_manifest(FakeSession(ROWS), version="v1")
    assert m.version == "v1"
    assert m.total_chunks == 20
    assert m.documents[0].sutta_uid == "mn10"


def test_verify_manifest_passes_on_identical_corpus():
    m = build_manifest(FakeSession(ROWS), version="v1")
    assert verify_manifest(FakeSession(ROWS), m) == []


def test_verify_manifest_reports_drift():
    m = build_manifest(FakeSession(ROWS), version="v1")
    drifted = [(1, "MN 10: Satipatthana", "mn10", 12, "CHANGED"), ROWS[1]]
    problems = verify_manifest(FakeSession(drifted), m)
    assert problems and "mn10" in problems[0]


def test_manifest_json_roundtrip(tmp_path):
    m = build_manifest(FakeSession(ROWS), version="v1")
    path = tmp_path / "manifest.json"
    m.save(path)
    assert CorpusManifest.load(path).total_chunks == 20


def test_uid_to_document_ids_maps_and_skips_missing():
    rows = ROWS + [(3, "Untitled import", None, 4, "ccc")]
    m = build_manifest(FakeSession(rows), version="v1")
    mapping = m.uid_to_document_ids()
    assert mapping == {"mn10": [1], "mn118": [2]}
