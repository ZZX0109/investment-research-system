"""Contract for the long-term investor research track.

This is intentionally separate from the short-horizon research tasks. It
describes what a retraining run is allowed to claim, rather than pretending
that a one/ five/ twenty-day classifier is a long-term investing model.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator


class LongTermTrainingConfig(BaseModel):
    schema_version: str = "long-term-training-config-v1"
    profile: str = "long_term_investment_quality"
    label_policy: str = "pit-available-quarterly-fundamentals-v2"
    # Kept separate from the snapshot and feature contract so relabelling can
    # invalidate only labels/downstream artifacts rather than the whole data
    # snapshot.  ``label_policy`` remains the human-readable policy name.
    label_version: str = "cn-long-term-label-v2"
    snapshot_frequency: str = "quarterly"
    snapshot_cadence: str = "quarter_end"
    primary_decision_unit: str = "symbol_quarter_end"
    short_horizon_role: str = "auxiliary_market_observation"
    feature_groups: list[str] = Field(
        default_factory=lambda: [
            "quality_and_balance_sheet",
            "cash_flow_and_growth",
            "valuation_relative_to_industry",
            "shareholder_returns_and_dilution",
            "industry_competition_and_market_state",
            "macro_and_liquidity",
            "events_and_corporate_actions",
        ],
        min_length=1,
    )
    horizons_days: list[int] = Field(default_factory=lambda: [120, 240, 480, 960], min_length=1)
    targets: list[str] = Field(
        default_factory=lambda: [
            "future_quality_persistence_4q",
            "future_quality_persistence_8q",
            "excess_return_120d",
            "excess_return_240d",
            "future_max_drawdown_120d",
            "future_max_drawdown_240d",
        ],
        min_length=1,
    )
    primary_targets: list[str] = Field(
        default_factory=lambda: [
            "excess_return_120d", "excess_return_240d",
            "future_max_drawdown_120d", "future_max_drawdown_240d",
        ],
        min_length=4,
    )
    auxiliary_targets: list[str] = Field(
        default_factory=lambda: [
            "future_quality_persistence_4q", "future_quality_persistence_8q",
        ],
        min_length=1,
    )
    required_snapshot_datasets: list[str] = Field(
        default_factory=lambda: [
            "daily_bars_raw",
            "daily_bars_qfq",
            "cn_trading_status",
            "cn_adjustment_factors_research",
            "cn_security_master_research",
            "cn_historical_universe_memberships",
            "cn_fundamentals_research",
            "cn_corporate_actions_research",
            "events",
            "cn_margin_financing_sh",
            "cn_margin_financing_sz",
            "cn_market_breadth_derived",
            "cn_macro_cpi_monthly",
            "cn_macro_ppi_monthly",
            "cn_macro_pmi_monthly",
            "cn_macro_lpr",
            "cn_macro_shibor",
            "cn_macro_m2",
            "cn_macro_social_financing",
            "cn_macro_fx_rmb",
            "cn_macro_pit",
        ],
        min_length=1,
    )
    evaluation_metrics: list[str] = Field(
        default_factory=lambda: [
            "rank_ic",
            "rank_icir",
            "top_k_excess_return",
            "top_bottom_spread",
            "top_k_excess_return_after_cost",
            "top_bottom_spread_after_cost",
            "pinball_loss",
            "mae",
            "interval_coverage",
            "turnover",
            "max_drawdown",
            "capacity",
            "year_stability",
            "industry_stability",
            "regime_stability",
            "data_completeness_stability",
            "calibration",
        ],
        min_length=1,
    )
    purge_days: int = Field(default=960, ge=0)
    embargo_days: int = Field(default=120, ge=0)
    purge_periods: int = Field(default=4, ge=0)
    embargo_periods: int = Field(default=1, ge=0)
    min_history_days: int = Field(default=1260, gt=0)
    train_window_periods: int = Field(default=24, gt=0)
    validation_periods: int = Field(default=4, gt=0)
    final_holdout_periods: int = Field(default=8, ge=4)
    stress_periods: int = Field(default=4, ge=2)
    minimum_shadow_sessions: int = Field(default=60, ge=60)
    minimum_financial_coverage: float = Field(default=0.95, ge=0.0, le=1.0)
    minimum_rank_ic: float = 0.02
    minimum_cost_adjusted_return: float = 0.0
    top_k: int = Field(default=20, gt=0)
    transaction_cost_bps: float = Field(default=15.0, ge=0.0)
    require_snapshot_gate: bool = True
    require_pit_financials: bool = True
    require_mature_labels: bool = True
    score_outputs: list[str] = Field(
        default_factory=lambda: [
            "long_term_quality", "growth_stability", "valuation_position",
            "shareholder_return", "long_term_risk", "evidence_completeness",
        ], min_length=1,
    )
    status_bands: dict[str, float] = Field(
        default_factory=lambda: {"robust": 70.0, "observe": 45.0}
    )

    @model_validator(mode="after")
    def validate_contract(self) -> "LongTermTrainingConfig":
        if any(h <= 0 for h in self.horizons_days):
            raise ValueError("horizons_days must contain positive trading-day horizons")
        longest = max(self.horizons_days)
        if self.purge_days < longest:
            raise ValueError("purge_days must cover the longest forward label horizon")
        if self.min_history_days < longest:
            raise ValueError("min_history_days must cover the longest forward label horizon")
        if "rank_ic" not in self.evaluation_metrics:
            raise ValueError("long-term ranking must be evaluated with rank_ic")
        required_metrics = {
            "rank_ic", "rank_icir", "top_k_excess_return",
            "top_bottom_spread", "top_k_excess_return_after_cost",
            "top_bottom_spread_after_cost", "pinball_loss", "mae",
            "interval_coverage", "turnover", "max_drawdown", "capacity",
            "year_stability", "industry_stability", "regime_stability",
            "data_completeness_stability", "calibration",
        }
        missing_metrics = sorted(required_metrics - set(self.evaluation_metrics))
        if missing_metrics:
            raise ValueError("long-term evaluation metrics missing: " + ",".join(missing_metrics))
        if "daily_bars_raw" not in self.required_snapshot_datasets or "daily_bars_qfq" not in self.required_snapshot_datasets:
            raise ValueError("required_snapshot_datasets must include raw and qfq daily bars")
        if self.snapshot_frequency not in {"quarterly", "monthly"}:
            raise ValueError("snapshot_frequency must be quarterly or monthly")
        if self.snapshot_cadence not in {"quarter_end", "month_end"}:
            raise ValueError("snapshot_cadence must be quarter_end or month_end")
        if self.stress_periods > self.final_holdout_periods:
            raise ValueError("stress_periods must be inside the final holdout")
        forbidden_short_horizon = re.compile(
            r"(?:^|_)(?:1|5|20)d(?:_|$)"
        )
        if any(
            forbidden_short_horizon.search(target)
            for target in self.targets
        ):
            raise ValueError("short-horizon targets are auxiliary only and cannot be in the long-term contract")
        required_primary = {
            "excess_return_120d", "excess_return_240d",
            "future_max_drawdown_120d", "future_max_drawdown_240d",
        }
        if not required_primary.issubset(self.primary_targets):
            missing_primary = sorted(required_primary - set(self.primary_targets))
            raise ValueError("long-term primary targets missing: " + ",".join(missing_primary))
        if not set(self.primary_targets).issubset(self.targets):
            raise ValueError("primary_targets must be included in targets")
        if not set(self.auxiliary_targets).issubset(self.targets):
            raise ValueError("auxiliary_targets must be included in targets")
        if set(self.primary_targets) & set(self.auxiliary_targets):
            raise ValueError("primary_targets and auxiliary_targets must be disjoint")
        if self.status_bands.get("robust", 100.0) <= self.status_bands.get("observe", 0.0):
            raise ValueError("robust status band must be above observe")
        return self

    def canonical_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(payload).hexdigest()


def load_long_term_training_config(path: Path) -> LongTermTrainingConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("long-term training config must be a mapping")
    return LongTermTrainingConfig.model_validate(payload)
