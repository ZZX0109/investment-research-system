from __future__ import annotations

import hashlib
import json
from datetime import date
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class PipelineMode(str, Enum):
    FORMAL = "formal"
    RESEARCH = "research"
    REPLAY = "replay"
    TEST = "test"


class ModelTask(str, Enum):
    RISK = "risk"
    RETURN = "return"
    DIRECTION = "direction"


class ReleaseScope(BaseModel):
    market: str
    decision_context: str
    task: ModelTask

    @property
    def key(self) -> str:
        return f"{self.market}:{self.decision_context}:{self.task.value}"


class ProviderConfig(BaseModel):
    primary: str
    backup: str | None = None
    authorized: bool = False
    sla_name: str | None = None
    authorization_ref: str | None = None
    catalog_ref: str | None = None
    supports_historical_pit: bool = False
    supports_revisions: bool = False
    historical_time_fields: list[str] = Field(default_factory=list)
    # Formal scheduling must use an exchange calendar reference rather than a
    # weekday approximation.  The reference is deployment configuration, not
    # a free-data fallback.
    exchange_calendar_ref: str | None = None


class CacheTtlConfig(BaseModel):
    daily_bars_seconds: int = Field(default=86400, gt=0)
    events_seconds: int = Field(default=3600, gt=0)
    snapshots_seconds: int = Field(default=15, gt=0)


class TrainingPipelineConfig(BaseModel):
    schema_version: str = "training-pipeline-config-v2"
    mode: PipelineMode
    markets: list[str] = Field(min_length=1)
    start_date: date
    end_date: date
    decision_context: str = "close_confirmed"
    decision_contexts: list[str] = Field(default_factory=lambda: ["close_confirmed", "pre_open"])
    tasks: list[ModelTask] = Field(default_factory=lambda: [ModelTask.RISK, ModelTask.RETURN, ModelTask.DIRECTION])
    targets: list[str] = Field(default_factory=lambda: ["future_max_drawdown_20d"])
    train_window_days: int = Field(default=504, gt=0)
    validation_window_days: int = Field(default=126, gt=0)
    final_holdout_days: int = Field(default=252, ge=252)
    recent_stress_days: int = Field(default=126, ge=126)
    embargo_days: int = Field(default=20, ge=0)
    random_seeds: list[int] = Field(default_factory=lambda: [42])
    feature_contract_version: str = "investment-risk-features-v2"
    label_policy_version: str = "four-market-tradeable-label-v1"
    adjustment_policy: str = "qfq-labels_raw-market-state"
    providers: dict[str, ProviderConfig]
    cache_ttl: CacheTtlConfig = Field(default_factory=CacheTtlConfig)
    output_root: Path = Path("artifacts/training")
    deployment_root: Path = Path("output/models")
    allow_synthetic: bool = False
    training_profile: str = "full"
    minimum_shadow_sessions: int = Field(default=20, ge=20)
    minimum_critical_coverage: float = Field(default=0.98, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_formal_contract(self) -> "TrainingPipelineConfig":
        if self.end_date < self.start_date:
            raise ValueError("end_date cannot precede start_date")
        if self.mode == PipelineMode.FORMAL:
            if self.allow_synthetic:
                raise ValueError("formal pipeline cannot allow synthetic data")
            missing = [market for market in self.markets if market not in self.providers]
            if missing:
                raise ValueError(f"formal pipeline has no provider config for: {missing}")
        if self.embargo_days < max(_target_horizon(item) for item in self.targets):
            raise ValueError("embargo_days must cover the longest target horizon")
        if set(self.decision_contexts) != {"close_confirmed", "pre_open"}:
            raise ValueError("formal four-market rebuild requires independent close_confirmed and pre_open contexts")
        if self.recent_stress_days > self.final_holdout_days:
            raise ValueError("recent stress slice must be inside the final holdout")
        return self

    def release_scopes(self) -> list[ReleaseScope]:
        return [
            ReleaseScope(market=market, decision_context=context, task=task)
            for market in self.markets
            for context in self.decision_contexts
            for task in self.tasks
        ]

    def canonical_hash(self) -> str:
        payload = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def run_root(self, training_run_id: str) -> Path:
        return self.output_root / self.mode.value / "runs" / training_run_id


def load_training_pipeline_config(path: Path) -> TrainingPipelineConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("training pipeline config must be a mapping")
    return TrainingPipelineConfig.model_validate(payload)


def _target_horizon(target: str) -> int:
    for horizon in (120, 60, 20, 10, 5, 3, 1):
        if f"{horizon}d" in target:
            return horizon
    return 1
