from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class MarketQuote(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    asset_id: UUID
    provider: str
    quote_at: datetime
    fetched_at: datetime
    last_price: float = Field(gt=0)
    previous_close: float | None = Field(default=None, gt=0)
    payload_hash: str = Field(min_length=64, max_length=64)


class MarketQuoteAttempt(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    asset_id: UUID
    provider: str
    state: Literal["succeeded", "failed", "skipped"]
    attempted_at: datetime
    error_code: str | None = None
    error_message: str | None = None


class ObservationRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    observation_id: UUID
    revision: int = Field(ge=1)
    reason: Literal["corporate_action", "provider_correction", "manual_review"]
    payload_hash: str = Field(min_length=64, max_length=64)
    payload: dict[str, Any]
    created_at: datetime


class DirectionalForecast(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    analysis_run_id: UUID
    asset_id: UUID
    status: Literal["research_only", "approved"] = "research_only"
    direction: Literal["up", "down", "flat"] | None = None
    expected_return_low: float | None = None
    expected_return_high: float | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)
    model_version: str | None = None
    feature_coverage: float = Field(default=0.0, ge=0, le=1)
    gating_reasons: list[str] = Field(default_factory=list)
