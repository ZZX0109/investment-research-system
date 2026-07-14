from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class SourceLayerMetadata(BaseModel):
    mode: str = "real"
    provider: str = "unknown"
    as_of: datetime | None = None
    overrides: list[str] = Field(default_factory=list)
    synthetic_ratio: float = 0.0
