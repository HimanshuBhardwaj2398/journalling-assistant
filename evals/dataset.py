"""Eval dataset models and JSONL IO for retrieval evaluation.

Schema per docs/plans/2026-07-13-retrieval-eval-strategy-design.md §5.
Ground truth is anchored at two levels: chunk UUIDs (primary, IR metrics)
and sutta UIDs (stable across re-chunking).
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class QuestionType(str, Enum):
    FACTUAL = "factual"
    CONCEPTUAL = "conceptual"
    PRACTICAL = "practical"
    CROSS_TEXTUAL = "cross_textual"
    PALI_SPECIFIC = "pali_specific"


class Persona(str, Enum):
    NEW_MEDITATOR = "new_meditator"
    EXPERIENCED_PRACTITIONER = "experienced_practitioner"
    SCHOLAR = "scholar"


class Register(str, Enum):
    COLLOQUIAL = "colloquial"  # everyday language, no Pali/technical vocabulary
    CANONICAL = "canonical"  # may use the texts' own terminology


class Dimensions(BaseModel):
    question_type: QuestionType
    persona: Persona
    register: Register


class EvalRow(BaseModel):
    id: str
    question: str
    reference_answer: Optional[str] = None
    sutta_uids: list[str] = Field(default_factory=list)
    chunk_uuids: list[str] = Field(default_factory=list)
    source_document_ids: list[int] = Field(default_factory=list)
    dimensions: Dimensions
    origin: Literal["manual", "synthetic"]
    model_version: Optional[str] = None

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("question must not be blank")
        return v.strip()

    @model_validator(mode="after")
    def _has_ground_truth(self) -> "EvalRow":
        if not (self.sutta_uids or self.chunk_uuids or self.source_document_ids):
            raise ValueError("row needs at least one ground-truth anchor")
        return self


def load_dataset(path: str | Path) -> list[EvalRow]:
    """Load and validate a JSONL eval dataset. Raises on any invalid row."""
    rows = [
        EvalRow.model_validate_json(line)
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]
    ids = [r.id for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("dataset contains duplicate row ids")
    return rows


def save_dataset(rows: list[EvalRow], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row.model_dump(mode="json"), ensure_ascii=False) + "\n")
