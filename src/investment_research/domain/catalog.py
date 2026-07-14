from __future__ import annotations

from pydantic import BaseModel, Field


class DataModePolicySummary(BaseModel):
    data_mode: str
    allowed_source_types: list[str]
    description: str
    judge_gate_reason: str | None = None


class AnalysisProviderConfig(BaseModel):
    market_data_provider: str
    evidence_provider: str


class AnalysisProviderSummary(BaseModel):
    provider_name: str
    provider_version: str
    kind: str


class DomainCatalog(BaseModel):
    entities: list[str] = Field(default_factory=list)
    data_modes: list[str] = Field(default_factory=list)
    data_source_types: list[str] = Field(default_factory=list)
    mode_policies: list[DataModePolicySummary] = Field(default_factory=list)
    analysis_provider_config: AnalysisProviderConfig
    analysis_providers: list[AnalysisProviderSummary] = Field(default_factory=list)
    principles: list[str] = Field(default_factory=list)
