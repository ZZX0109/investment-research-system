from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from investment_research.domain.enums import AssetType, DataMode, DataSourceType


class AssetCreateRequest(BaseModel):
    ticker: str = Field(min_length=1)
    name: str = Field(min_length=1)
    asset_type: AssetType
    currency: str = Field(default="USD", min_length=3, max_length=3)
    exchange: str | None = None
    data_mode: DataMode
    source_type: DataSourceType
    source_name: str = Field(min_length=1)
    observed_at: datetime
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class PositionCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    quantity: float = Field(gt=0.0)
    cost_basis: float = Field(ge=0.0)
    opened_at: datetime


class WatchlistCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    asset_ids: list[str] = Field(default_factory=list)


class PricePointInput(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class PriceSeriesCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    interval: str = Field(min_length=2)
    data_mode: DataMode
    source_type: DataSourceType
    source_name: str = Field(min_length=1)
    observed_at: datetime
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    series_role: Literal["asset", "benchmark", "sector", "style"] = "asset"
    reference_symbol: str | None = None
    points: list[PricePointInput] = Field(min_length=1)


class EvidenceCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    evidence_type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_url: str | None = None
    collected_at: datetime
    published_at: datetime | None = None
    payload_ref: str | None = None
    event_type: str | None = None
    direction: str | None = None
    intensity: str | None = None
    source_tier: str | None = None
    surprise_bucket: str | None = None
    guidance_bucket: str | None = None
    filing_type: str | None = None
    raw_hash: str | None = None
    normalized_hash: str | None = None
    data_version: str | None = None
    data_mode: DataMode
    source_type: DataSourceType
    source_name: str = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ResearchReportCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    analysis_run_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    thesis: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    report_version: str = Field(min_length=1)
    data_mode: DataMode
    source_type: DataSourceType
    source_name: str = Field(min_length=1)
    observed_at: datetime
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class AssetRefreshRequest(BaseModel):
    refresh_mode: Literal["online", "cache", "auto"] = "auto"


class ReportScheduleCreateRequest(BaseModel):
    asset_id: str | None = None
    frequency: Literal["manual", "daily", "weekly", "monthly", "event_triggered"] = (
        "manual"
    )
    enabled: bool = True
    timezone: str = "Asia/Shanghai"


class ReportScheduleUpdateRequest(BaseModel):
    frequency: (
        Literal["manual", "daily", "weekly", "monthly", "event_triggered"] | None
    ) = None
    enabled: bool | None = None


class ClaimCreateRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    direction: Literal["positive", "neutral", "negative", "unknown"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str] = Field(min_length=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    contrary_claim_id: str | None = None
    supersedes_claim_id: str | None = None


class ClaimReviewRequest(BaseModel):
    status: Literal["verified", "rejected"]


class ResourceShareCreateRequest(BaseModel):
    viewer_email: str = Field(min_length=3)
