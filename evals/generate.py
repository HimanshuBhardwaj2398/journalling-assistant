"""Dimension-based synthetic QA generation with binary critics.

Design: docs/plans/2026-07-13-retrieval-eval-strategy-design.md §5.
LLM discipline: every call returns JSON parsed with one retry, then dead-letter
(row skipped and logged) — never parse free text.

CLI (requires DATABASE_URL, LLM provider key, VOYAGE_API_KEY):
    poetry run python -m evals.generate --target 150 --out data/evals/retrieval_v1.jsonl
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field

from evals.dataset import Dimensions, EvalRow, Persona, QuestionType, Register

logger = logging.getLogger(__name__)

QUESTION_TYPE_WEIGHTS = {
    QuestionType.FACTUAL: 0.25,
    QuestionType.CONCEPTUAL: 0.25,
    QuestionType.PRACTICAL: 0.25,
    QuestionType.CROSS_TEXTUAL: 0.15,
    QuestionType.PALI_SPECIFIC: 0.10,
}

QTYPE_INSTRUCTIONS = {
    QuestionType.FACTUAL: "a lookup question with a specific answer stated in the passage",
    QuestionType.CONCEPTUAL: "a question about meaning or relationships between ideas",
    QuestionType.PRACTICAL: "a how-to question about actually practicing",
    QuestionType.CROSS_TEXTUAL: "a question whose full answer spans related teachings",
    QuestionType.PALI_SPECIFIC: "a question that uses a Pali term from the passage",
}

PERSONA_INSTRUCTIONS = {
    Persona.NEW_MEDITATOR: "a beginner meditator with no knowledge of Buddhist terminology",
    Persona.EXPERIENCED_PRACTITIONER: "an experienced practitioner familiar with the teachings",
    Persona.SCHOLAR: "a scholar of early Buddhist texts",
}

REGISTER_INSTRUCTIONS = {
    Register.COLLOQUIAL: (
        "Use everyday language ONLY. Do NOT use any Pali words or technical Buddhist "
        "terms, even if the passage uses them — phrase it the way a regular person would."
    ),
    Register.CANONICAL: "You may use the passage's own terminology, including Pali terms.",
}

GENERATION_PROMPT = """You write evaluation questions for a Buddhist-texts search system.

Given a passage, write ONE question that {persona} might ask, and a concise answer
grounded strictly in the passage.

Question style: {qtype}.
{register}

Rules:
- The question must be answerable from the passage.
- Never mention "the passage", "the text", or "the author".
- The question must make sense on its own, without seeing the passage.

Passage:
{chunk}

Reply with ONLY valid JSON: {{"question": "...", "answer": "..."}}"""

CRITIC_PROMPTS = {
    "grounded": (
        "Can this question be answered from the passage alone?\n\n"
        "Passage:\n{chunk}\n\nQuestion: {question}\nProposed answer: {answer}\n\n"
        'Reply with ONLY valid JSON: {{"pass": true/false, "critique": "one line"}}'
    ),
    "standalone": (
        "Can this question be fully understood by someone who has NOT seen the source passage? "
        "It must not refer to 'the passage/text' or depend on unstated context.\n\n"
        "Question: {question}\n\n"
        'Reply with ONLY valid JSON: {{"pass": true/false, "critique": "one line"}}'
    ),
    "realistic": (
        "Would a real meditation practitioner or student of Buddhism plausibly ask this "
        "question? Judge whether it sounds like a genuine query, not a quiz item.\n\n"
        "Question: {question}\n\n"
        'Reply with ONLY valid JSON: {{"pass": true/false, "critique": "one line"}}'
    ),
}


@dataclass
class ChunkSample:
    chunk_uuid: str
    document_id: int
    sutta_uid: str | None
    nikaya: str | None
    text: str


@dataclass
class CriticVerdict:
    passed: bool
    critiques: dict[str, str] = field(default_factory=dict)


def parse_json_with_retry(client, messages: list[dict]) -> dict | None:
    """One retry on invalid JSON, then dead-letter (None). Strips ```json fences."""
    for attempt in range(2):
        raw = client.complete(messages=messages, temperature=0.3, max_tokens=400)
        cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            if attempt == 0:
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": "That was not valid JSON. Reply with ONLY the JSON object.",
                    },
                ]
    logger.warning("dead-letter: invalid JSON after retry")
    return None


def dimension_deck(n: int, seed: int = 42) -> list[Dimensions]:
    """Deterministic list of dimension tuples matching the target distribution."""
    rng = random.Random(seed)
    qtypes = rng.choices(
        list(QUESTION_TYPE_WEIGHTS), weights=list(QUESTION_TYPE_WEIGHTS.values()), k=n
    )
    personas = [list(Persona)[i % len(Persona)] for i in range(n)]
    deck = []
    for i, (qt, persona) in enumerate(zip(qtypes, personas)):
        register = (
            Register.CANONICAL
            if qt == QuestionType.PALI_SPECIFIC
            else (Register.COLLOQUIAL if i % 2 == 0 else Register.CANONICAL)
        )
        deck.append(Dimensions(question_type=qt, persona=persona, register=register))
    return deck


def generate_row(client, chunk: ChunkSample, dims: Dimensions, row_id: str) -> EvalRow | None:
    prompt = GENERATION_PROMPT.format(
        persona=PERSONA_INSTRUCTIONS[dims.persona],
        qtype=QTYPE_INSTRUCTIONS[dims.question_type],
        register=REGISTER_INSTRUCTIONS[dims.register],
        chunk=chunk.text,
    )
    data = parse_json_with_retry(client, [{"role": "user", "content": prompt}])
    if not data or not data.get("question") or not data.get("answer"):
        return None
    return EvalRow(
        id=row_id,
        question=data["question"],
        reference_answer=data["answer"],
        sutta_uids=[chunk.sutta_uid] if chunk.sutta_uid else [],
        chunk_uuids=[chunk.chunk_uuid],
        source_document_ids=[chunk.document_id],
        dimensions=dims,
        origin="synthetic",
        model_version=client.model_id,
    )


def run_critics(client, question: str, answer: str, chunk_text: str) -> CriticVerdict:
    critiques: dict[str, str] = {}
    passed = True
    for name, template in CRITIC_PROMPTS.items():
        prompt = template.format(chunk=chunk_text, question=question, answer=answer)
        data = parse_json_with_retry(client, [{"role": "user", "content": prompt}])
        if data is None:
            return CriticVerdict(passed=False, critiques={name: "dead-letter"})
        critiques[name] = data.get("critique", "")
        passed = passed and bool(data.get("pass"))
    return CriticVerdict(passed=passed, critiques=critiques)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def dedup_rows(
    rows: list[EvalRow], embeddings: list[list[float]], threshold: float = 0.9
) -> list[EvalRow]:
    """Greedy near-duplicate removal by question-embedding cosine similarity."""
    kept: list[int] = []
    for i in range(len(rows)):
        if all(_cosine(embeddings[i], embeddings[j]) < threshold for j in kept):
            kept.append(i)
    return [rows[i] for i in kept]


def sample_chunks(session, target: int, seed: int = 42) -> list[ChunkSample]:
    """Stratified sampling: proportional per nikaya, random within, min chunk length 300."""
    from sqlalchemy import text as sql

    rows = session.execute(
        sql(
            """
            SELECT c.uuid, c.document_id, d.doc_metadata->>'uid', d.doc_metadata->>'nikaya',
                   c.chunk_text
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE d.status = 'completed' AND length(c.chunk_text) >= 300
            """
        )
    ).fetchall()
    by_nikaya: dict[str, list] = {}
    for r in rows:
        by_nikaya.setdefault(r[3] or "unknown", []).append(r)
    rng = random.Random(seed)
    total = sum(len(v) for v in by_nikaya.values())
    samples: list[ChunkSample] = []
    for _nikaya, group in sorted(by_nikaya.items()):
        n = max(1, round(target * len(group) / total))
        for r in rng.sample(group, min(n, len(group))):
            samples.append(
                ChunkSample(
                    chunk_uuid=r[0], document_id=r[1], sutta_uid=r[2], nikaya=r[3], text=r[4]
                )
            )
    return samples[:target]


def main() -> None:  # pragma: no cover - thin CLI; components tested above
    import argparse

    from langchain_voyageai import VoyageAIEmbeddings

    from db.database import session_scope
    from evals.dataset import load_dataset, save_dataset
    from retrieval.llm_client import LLMClient

    parser = argparse.ArgumentParser(description="Generate the synthetic eval dataset")
    parser.add_argument("--target", type=int, default=150, help="chunks to sample")
    parser.add_argument("--out", default="data/evals/retrieval_v1.jsonl")
    parser.add_argument("--seed-file", default="data/evals/manual_seed.jsonl")
    parser.add_argument("--dedup-threshold", type=float, default=0.9)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    client = LLMClient()
    with session_scope() as session:
        chunks = sample_chunks(session, target=args.target)
    logger.info("sampled %d chunks", len(chunks))

    deck = dimension_deck(n=len(chunks))
    candidates: list[EvalRow] = []
    for i, (chunk, dims) in enumerate(zip(chunks, deck), start=1):
        row = generate_row(client, chunk, dims, row_id=f"syn_{i:03d}")
        if row is None:
            continue
        verdict = run_critics(client, row.question, row.reference_answer or "", chunk.text)
        if verdict.passed:
            candidates.append(row)
        else:
            logger.info("filtered %s: %s", row.id, verdict.critiques)
    logger.info("%d/%d candidates passed critics", len(candidates), len(chunks))

    embedder = VoyageAIEmbeddings(model="voyage-3.5")
    vectors = embedder.embed_documents([r.question for r in candidates])
    synthetic = dedup_rows(candidates, vectors, threshold=args.dedup_threshold)
    logger.info("%d rows after dedup", len(synthetic))

    seeds = load_dataset(args.seed_file)
    save_dataset(seeds + synthetic, args.out)
    logger.info(
        "wrote %d rows (%d seed + %d synthetic) -> %s",
        len(seeds) + len(synthetic),
        len(seeds),
        len(synthetic),
        args.out,
    )


if __name__ == "__main__":
    main()
