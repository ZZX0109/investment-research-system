from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DirectionLabel = Literal["up", "down", "flat"]


class DirectionLabelPolicy(BaseModel):
    """Versioned research label policy; it is independent from drawdown risk."""

    version: str = "future-return-20d-direction-v1"
    horizon_trading_days: int = 20
    up_threshold: float = 0.02
    down_threshold: float = -0.02
    volatility_standardized: bool = False
    standardized_threshold: float = 0.5
    minimum_volatility: float = 0.005
    transaction_cost: float = 0.0
    instrument_multipliers: dict[str, float] = Field(default_factory=lambda: {"equity": 1.0, "etf": 0.8, "index": 0.7})

    def classify(
        self,
        future_return_20d: float,
        *,
        trailing_volatility_20d: float | None = None,
        instrument_type: str = "equity",
        market_state_multiplier: float = 1.0,
    ) -> DirectionLabel:
        up_threshold, down_threshold = self.thresholds(
            trailing_volatility_20d=trailing_volatility_20d,
            instrument_type=instrument_type,
            market_state_multiplier=market_state_multiplier,
        )
        if future_return_20d >= up_threshold:
            return "up"
        if future_return_20d <= down_threshold:
            return "down"
        return "flat"

    def thresholds(
        self,
        *,
        trailing_volatility_20d: float | None,
        instrument_type: str,
        market_state_multiplier: float,
    ) -> tuple[float, float]:
        if not self.volatility_standardized or trailing_volatility_20d is None:
            return self.up_threshold, self.down_threshold
        volatility = max(self.minimum_volatility, trailing_volatility_20d)
        multiplier = self.instrument_multipliers.get(instrument_type, 1.0) * max(0.1, market_state_multiplier)
        boundary = (self.standardized_threshold * volatility * multiplier) + self.transaction_cost
        return boundary, -boundary


class DirectionLabelOutcome(BaseModel):
    label: DirectionLabel
    raw_return: float
    standardized_return: float | None = None
    maximum_adverse_excursion: float | None = None
    maximum_favorable_excursion: float | None = None
    touched_limit_up: bool = False
    touched_limit_down: bool = False
    policy_version: str


class DirectionEvaluation(BaseModel):
    macro_f1: float = Field(ge=0, le=1)
    balanced_accuracy: float = Field(ge=0, le=1)
    log_loss: float = Field(ge=0)
    ece: float = Field(ge=0, le=1)
    market_macro_f1: dict[str, float] = Field(default_factory=dict)
    regime_macro_f1: dict[str, float] = Field(default_factory=dict)
    recent_window_macro_f1: list[float] = Field(default_factory=list)
    shared_sample_hash: str
    shared_fold_hash: str


class DirectionPromotionPolicy(BaseModel):
    min_macro_f1: float = 0.45
    min_balanced_accuracy: float = 0.45
    max_log_loss: float = 1.05
    max_ece: float = 0.15
    min_market_macro_f1: float = 0.35
    min_regime_macro_f1: float = 0.35
    min_recent_macro_f1: float = 0.40

    def evaluate(self, metrics: DirectionEvaluation) -> list[str]:
        reasons: list[str] = []
        if metrics.macro_f1 < self.min_macro_f1:
            reasons.append("macro_f1_below_gate")
        if metrics.balanced_accuracy < self.min_balanced_accuracy:
            reasons.append("balanced_accuracy_below_gate")
        if metrics.log_loss > self.max_log_loss:
            reasons.append("log_loss_above_gate")
        if metrics.ece > self.max_ece:
            reasons.append("calibration_ece_above_gate")
        if not metrics.market_macro_f1 or any(value < self.min_market_macro_f1 for value in metrics.market_macro_f1.values()):
            reasons.append("market_gate_failed")
        if not metrics.regime_macro_f1 or any(value < self.min_regime_macro_f1 for value in metrics.regime_macro_f1.values()):
            reasons.append("regime_gate_failed")
        if len(metrics.recent_window_macro_f1) < 2 or any(value < self.min_recent_macro_f1 for value in metrics.recent_window_macro_f1[-2:]):
            reasons.append("recent_window_gate_failed")
        return reasons


class DirectionalModelManifest(BaseModel):
    schema_version: str = "directional-model-manifest-v1"
    status: Literal["research_only", "approved"] = "research_only"
    model_name: str
    model_version: str
    label_policy: DirectionLabelPolicy = Field(default_factory=DirectionLabelPolicy)
    evaluation: DirectionEvaluation
    gating_reasons: list[str] = Field(default_factory=list)

    @classmethod
    def from_evaluation(
        cls,
        *,
        model_name: str,
        model_version: str,
        evaluation: DirectionEvaluation,
        policy: DirectionPromotionPolicy | None = None,
    ) -> "DirectionalModelManifest":
        reasons = (policy or DirectionPromotionPolicy()).evaluate(evaluation)
        return cls(
            model_name=model_name,
            model_version=model_version,
            evaluation=evaluation,
            status="approved" if not reasons else "research_only",
            gating_reasons=reasons,
        )
