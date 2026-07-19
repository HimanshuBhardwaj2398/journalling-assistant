"""Eval corpus manifest: freeze the corpus snapshot evals are valid against.

Per-document chunk-UUID md5 lets `verify_manifest` detect re-chunking without
storing every UUID. Sutta uid comes from doc_metadata (SuttaCentral ingestion
stores `uid`/`nikaya` in parse metadata).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import text

MANIFEST_SQL = text(
    """
    SELECT d.id, d.title, d.doc_metadata->>'uid' AS sutta_uid,
           count(c.id) AS chunk_count,
           md5(string_agg(c.uuid, ',' ORDER BY c.uuid)) AS chunk_md5
    FROM documents d
    JOIN chunks c ON c.document_id = d.id
    WHERE d.status = 'completed'
    GROUP BY d.id, d.title, sutta_uid
    ORDER BY d.id
    """
)


class ManifestDoc(BaseModel):
    document_id: int
    title: str
    sutta_uid: Optional[str] = None
    chunk_count: int
    chunk_md5: str


class CorpusManifest(BaseModel):
    version: str
    created_at: str
    total_chunks: int
    documents: list[ManifestDoc]

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "CorpusManifest":
        return cls.model_validate_json(Path(path).read_text())

    def uid_to_document_ids(self) -> dict[str, list[int]]:
        """Map sutta uid -> document ids (runner resolves seed-row anchors with this)."""
        out: dict[str, list[int]] = {}
        for doc in self.documents:
            if doc.sutta_uid:
                out.setdefault(doc.sutta_uid, []).append(doc.document_id)
        return out


def _fetch(session) -> list[ManifestDoc]:
    rows = session.execute(MANIFEST_SQL).fetchall()
    return [
        ManifestDoc(document_id=r[0], title=r[1], sutta_uid=r[2], chunk_count=r[3], chunk_md5=r[4])
        for r in rows
    ]


def build_manifest(session, version: str) -> CorpusManifest:
    docs = _fetch(session)
    return CorpusManifest(
        version=version,
        created_at=datetime.now(timezone.utc).isoformat(),
        total_chunks=sum(d.chunk_count for d in docs),
        documents=docs,
    )


def verify_manifest(session, manifest: CorpusManifest) -> list[str]:
    """Return human-readable drift problems; empty list means the corpus still matches."""
    current = {d.document_id: d for d in _fetch(session)}
    problems = []
    for doc in manifest.documents:
        live = current.get(doc.document_id)
        if live is None:
            problems.append(f"document {doc.document_id} ({doc.sutta_uid}) missing from corpus")
        elif (live.chunk_count, live.chunk_md5) != (doc.chunk_count, doc.chunk_md5):
            problems.append(
                f"document {doc.document_id} ({doc.sutta_uid}) was re-chunked "
                f"({doc.chunk_count}->{live.chunk_count} chunks)"
            )
    return problems


def main() -> None:  # pragma: no cover - thin CLI
    import argparse

    from db.database import session_scope

    parser = argparse.ArgumentParser(description="Freeze the eval corpus manifest")
    parser.add_argument("--version", default="v1")
    parser.add_argument("--out", default="data/evals/corpus_manifest_v1.json")
    args = parser.parse_args()

    with session_scope() as session:
        manifest = build_manifest(session, version=args.version)
    manifest.save(args.out)
    print(
        f"Froze {len(manifest.documents)} documents / {manifest.total_chunks} chunks -> {args.out}"
    )


if __name__ == "__main__":
    main()
