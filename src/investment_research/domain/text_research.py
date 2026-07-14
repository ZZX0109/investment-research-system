from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TextResearchRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    symbol: str
    market: Literal["cn", "us", "hk", "jp"]
    source_ref: str
    first_published_at: datetime
    received_at: datetime
    processed_at: datetime
    model_version: str
    event_class: str
    sentiment: float = Field(ge=-1, le=1)
    subjects: list[str] = Field(default_factory=list)
    impact_direction: Literal["positive", "neutral", "negative", "unknown"]
    embedding_hash: str = Field(min_length=64, max_length=64)

    @staticmethod
    def hash_embedding(values: list[float]) -> str:
        return sha256(
            ",".join(f"{value:.10g}" for value in values).encode()
        ).hexdigest()


def late_fusion(
    price_probability: float,
    text_probability: float,
    *,
    text_coverage: float,
    text_weight: float = 0.25,
) -> float:
    if not 0 <= text_coverage <= 1:
        raise ValueError("text coverage must be in [0, 1]")
    effective_weight = text_weight * text_coverage
    return min(
        1.0,
        max(
            0.0,
            price_probability * (1.0 - effective_weight)
            + text_probability * effective_weight,
        ),
    )
