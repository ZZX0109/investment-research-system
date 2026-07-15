"""Immutable, file-backed shadow evidence for public-data research.

This is deliberately separate from ``ShadowRunController``.  Research shadow
sessions help compare models and backfill outcomes, but they never contribute
to a formal release gate.
"""
from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from investment_research.domain.data_tier import DataTier, RESEARCH_VISIBILITY_ASSUMPTION
from investment_research.domain.pit import EventCoverageStatus


class ResearchShadowSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    market: Literal["cn", "us", "hk", "jp"]
    decision_context: Literal["close_confirmed", "pre_open"]
    symbol: str = "MARKET"
    cohort: Literal["cn_equity_core", "cn_etf_benchmark"] = "cn_equity_core"
    task: Literal["bundle", "direction_1d", "direction_5d", "return_20d", "drawdown_20d"] = "bundle"
    trade_date: date
    frozen_at: datetime
    market_snapshot_id: str
    market_snapshot_hash: str = Field(min_length=64, max_length=64)
    data_tier: DataTier = DataTier.RESEARCH_PIT
    historical_visibility_assumption: str = RESEARCH_VISIBILITY_ASSUMPTION
    coverage_ratio: float = Field(ge=0, le=1)
    event_coverage_status: EventCoverageStatus
    provider_chain: list[str] = Field(default_factory=list)
    provider_switch_count: int = Field(default=0, ge=0)
    model_artifact_hashes: dict[str, str] = Field(default_factory=dict)
    roster_hash: str | None = Field(default=None, min_length=64, max_length=64)
    model_candidate: str | None = None
    frozen_prediction: dict[str, Any] = Field(default_factory=dict)
    candidate_predictions: dict[str, Any] = Field(default_factory=dict)
    ensemble_weights: dict[str, float] = Field(default_factory=dict)
    data_quality_mask: dict[str, float] = Field(default_factory=dict)
    event_missing_mask: dict[str, float] = Field(default_factory=dict)
    provider_id: str | None = None
    revision_id: str | None = None
    source_delay_seconds: float | None = None
    prediction_price: float | None = Field(default=None, gt=0)
    evidence_coverage: float = Field(default=0, ge=0, le=1)
    model_disagreement: float | None = Field(default=None, ge=0, le=1)
    influence_facts: list[str] = Field(default_factory=list)
    market_regime: Literal["bull", "bear", "range", "high_vol", "unknown"] = "unknown"
    cache_state: Literal["fresh", "stale_usable", "expired", "unavailable"] = "fresh"
    abstained: bool = False
    abstain_reasons: list[str] = Field(default_factory=list)
    evidence_valid: bool = False

    @model_validator(mode="after")
    def cannot_be_formal(self) -> "ResearchShadowSession":
        if self.data_tier != DataTier.RESEARCH_PIT:
            raise ValueError("research shadow sessions must be research_pit")
        if not self.abstained and not self.model_artifact_hashes:
            raise ValueError("non-abstained research shadows require model artifact hashes")
        expected = (
            self.coverage_ratio >= 0.85
            and self.cache_state not in {"expired", "unavailable"}
            and bool(self.model_artifact_hashes)
            and "provider_conflict" not in self.abstain_reasons
            and "research_model_artifact_hash_missing" not in self.abstain_reasons
        )
        if self.evidence_valid != expected:
            raise ValueError("research shadow evidence validity must be derived from frozen inputs")
        return self


class ResearchShadowOutcome(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    research_shadow_session_id: UUID
    horizon_sessions: Literal[1, 5, 20, 60]
    filled_at: datetime
    realized_return: float | None = None
    realized_max_drawdown: float | None = None
    mae: float | None = None
    mfe: float | None = None
    direction: Literal["up", "down", "flat", "unavailable"] = "unavailable"
    data_complete: bool = False
    suspended_during_window: bool = False
    limit_event_during_window: bool = False
    error_category: Literal[
        "data_error", "direction_error", "risk_level_error", "event_omission",
        "evidence_explanation_error", "correct_abstain", "incorrect_abstain", "correct", "pending",
    ] = "pending"
    direction_brier_score: float | None = Field(default=None, ge=0)
    risk_brier_score: float | None = Field(default=None, ge=0)
    return_absolute_error: float | None = Field(default=None, ge=0)


class ResearchShadowSummary(BaseModel):
    data_tier: DataTier = DataTier.RESEARCH_PIT
    research_only: bool = True
    session_count: int = Field(ge=0)
    answered_count: int = Field(ge=0)
    abstained_count: int = Field(ge=0)
    abstain_rate: float = Field(ge=0, le=1)
    average_coverage_ratio: float = Field(ge=0, le=1)
    completed_outcomes: dict[int, int] = Field(default_factory=dict)
    latest_trade_date: date | None = None
    valid_session_count: int = Field(default=0, ge=0)
    forward_report_20_status: Literal["pending", "ready"] = "pending"
    primary_change_60_status: Literal["blocked", "eligible_for_review"] = "blocked"


class FileResearchShadowStore:
    """Content-immutable local store used by the free-data scheduler and tests."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def freeze(self, session: ResearchShadowSession) -> ResearchShadowSession:
        path = self._session_path(session)
        return self._write_immutable(path, session, "research shadow session")

    def backfill(self, outcome: ResearchShadowOutcome) -> ResearchShadowOutcome:
        path = self.root / "outcomes" / str(outcome.research_shadow_session_id) / f"{outcome.horizon_sessions}.json"
        return self._write_immutable(path, outcome, "research shadow outcome")

    def list_sessions(
        self, *, market: str | None = None, decision_context: str | None = None,
        symbol: str | None = None, task: str | None = None,
    ) -> list[ResearchShadowSession]:
        base = self.root / "sessions"
        if not base.exists():
            return []
        output: list[ResearchShadowSession] = []
        for path in base.rglob("*.json"):
            item = ResearchShadowSession.model_validate_json(path.read_text(encoding="utf-8"))
            if market is not None and item.market != market:
                continue
            if decision_context is not None and item.decision_context != decision_context:
                continue
            if symbol is not None and item.symbol != symbol:
                continue
            if task is not None and item.task != task:
                continue
            output.append(item)
        return sorted(output, key=lambda item: (item.trade_date, item.symbol, item.task), reverse=True)

    def get_session(self, session_id: UUID) -> ResearchShadowSession | None:
        return next((item for item in self.list_sessions() if item.id == session_id), None)

    def list_outcomes(self, session_id: UUID) -> list[ResearchShadowOutcome]:
        base = self.root / "outcomes" / str(session_id)
        if not base.exists():
            return []
        return sorted(
            (ResearchShadowOutcome.model_validate_json(path.read_text(encoding="utf-8")) for path in base.glob("*.json")),
            key=lambda item: item.horizon_sessions,
        )

    def summarize(
        self, *, market: str | None = None, decision_context: str | None = None,
        symbol: str | None = None, task: str | None = None,
    ) -> ResearchShadowSummary:
        sessions = self.list_sessions(
            market=market, decision_context=decision_context, symbol=symbol, task=task
        )
        abstained = sum(item.abstained for item in sessions)
        completed = {horizon: 0 for horizon in (1, 5, 20, 60)}
        for session in sessions:
            for outcome in self.list_outcomes(session.id):
                if outcome.data_complete:
                    completed[outcome.horizon_sessions] += 1
        count = len(sessions)
        valid_dates = {item.trade_date for item in sessions if item.evidence_valid}
        return ResearchShadowSummary(
            session_count=count,
            answered_count=count - abstained,
            abstained_count=abstained,
            abstain_rate=abstained / count if count else 0,
            average_coverage_ratio=(sum(item.coverage_ratio for item in sessions) / count if count else 0),
            completed_outcomes=completed,
            latest_trade_date=max((item.trade_date for item in sessions), default=None),
            valid_session_count=len(valid_dates),
            forward_report_20_status="ready" if len(valid_dates) >= 20 else "pending",
            primary_change_60_status="eligible_for_review" if len(valid_dates) >= 60 else "blocked",
        )

    def generate_forward_report(
        self, *, minimum_sessions: Literal[20, 60], market: str = "cn",
        decision_context: str = "close_confirmed",
    ) -> Path:
        sessions = self.list_sessions(market=market, decision_context=decision_context)
        valid_dates = sorted({item.trade_date for item in sessions if item.evidence_valid})
        if len(valid_dates) < minimum_sessions:
            raise ValueError(f"research forward report requires {minimum_sessions} valid sessions")
        eligible_dates = set(valid_dates[:minimum_sessions])
        selected = [item for item in sessions if item.trade_date in eligible_dates and item.evidence_valid]
        outcomes = [
            (session, outcome)
            for session in selected
            for outcome in self.list_outcomes(session.id)
            if outcome.data_complete
        ]
        payload = {
            "schema_version": "cn-research-forward-report-v1",
            "data_tier": "research_pit", "status": "research_only",
            "minimum_sessions": minimum_sessions,
            "valid_session_count": len(valid_dates),
            "evaluated_trade_dates": [item.isoformat() for item in sorted(eligible_dates)],
            "session_count": len(selected), "outcome_count": len(outcomes),
            "abstain_rate": sum(item.abstained for item in selected) / len(selected),
            "direction_accuracy": _average([
                1.0 if outcome.error_category == "correct" else 0.0
                for session, outcome in outcomes if session.task.startswith("direction_")
            ]),
            "mean_return_absolute_error": _average([
                outcome.return_absolute_error for _session, outcome in outcomes
                if outcome.return_absolute_error is not None
            ]),
            "mean_risk_brier": _average([
                outcome.risk_brier_score for _session, outcome in outcomes
                if outcome.risk_brier_score is not None
            ]),
            "regime_counts": {
                regime: sum(item.market_regime == regime for item in selected)
                for regime in ("bull", "bear", "range", "high_vol", "unknown")
            },
            "primary_change_allowed": minimum_sessions >= 60,
        }
        digest = coverage_snapshot_hash(payload)
        path = self.root / "reports" / f"forward-{minimum_sessions}-{valid_dates[minimum_sessions - 1].isoformat()}-{digest[:12]}.json"
        return self._write_report_immutable(path, {**payload, "report_hash": digest})

    @staticmethod
    def _write_report_immutable(path: Path, payload: dict[str, Any]) -> Path:
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        if path.is_file() and path.read_text(encoding="utf-8") != encoded:
            raise ValueError("research forward report is immutable")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(encoded, encoding="utf-8")
        return path

    def _session_path(self, session: ResearchShadowSession) -> Path:
        safe_symbol = session.symbol.replace("/", "_")
        return (
            self.root / "sessions" / session.market / session.decision_context /
            session.cohort / session.task / safe_symbol / f"{session.trade_date.isoformat()}.json"
        )

    @staticmethod
    def _write_immutable(path: Path, item: BaseModel, label: str):
        if path.is_file():
            existing = type(item).model_validate_json(path.read_text(encoding="utf-8"))
            if existing.model_dump(mode="json") != item.model_dump(mode="json"):
                raise ValueError(f"{label} is immutable")
            return existing
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = item.model_dump_json(indent=2)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(encoded, encoding="utf-8")
        temporary.replace(path)
        return item


def coverage_snapshot_hash(coverage: dict[str, Any]) -> str:
    return sha256(json.dumps(coverage, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


class ResearchShadowController:
    """Freeze actual research predictions and derive transparent abstentions."""

    def __init__(self, store: FileResearchShadowStore) -> None:
        self.store = store

    def freeze_prediction(
        self, *, market: str, decision_context: str, cohort: str, task: str,
        symbol: str, trade_date: date, frozen_at: datetime,
        market_snapshot_id: str, market_snapshot_hash: str,
        prediction: dict[str, Any], prediction_price: float | None,
        model_artifact_hashes: dict[str, str], coverage_ratio: float,
        event_coverage_status: EventCoverageStatus, provider_chain: list[str],
        evidence_coverage: float = 0.0, model_disagreement: float | None = None,
        influence_facts: list[str] | None = None, cache_state: str = "fresh",
        provider_conflict: bool = False, out_of_distribution_ratio: float = 0.0,
        roster_hash: str | None = None, model_candidate: str | None = None,
        market_regime: str = "unknown", candidate_predictions: dict[str, Any] | None = None,
        ensemble_weights: dict[str, float] | None = None, data_quality_mask: dict[str, float] | None = None,
        event_missing_mask: dict[str, float] | None = None, provider_id: str | None = None,
        revision_id: str | None = None, source_delay_seconds: float | None = None,
    ) -> ResearchShadowSession:
        reasons: list[str] = []
        if coverage_ratio < 0.85:
            reasons.append("research_feature_coverage_below_85pct")
        if cache_state in {"expired", "unavailable"}:
            reasons.append(f"research_cache_{cache_state}")
        if provider_conflict:
            reasons.append("provider_conflict")
        if out_of_distribution_ratio > 0.20:
            reasons.append("out_of_distribution_feature_ratio_above_20pct")
        if not model_artifact_hashes or any(not value for value in model_artifact_hashes.values()):
            reasons.append("research_model_artifact_hash_missing")
        threshold = 0.30 if task.startswith("direction_") else 0.25 if task == "drawdown_20d" else 0.05 if task == "return_20d" else None
        if threshold is not None and model_disagreement is not None and model_disagreement > threshold:
            reasons.append("model_disagreement")
        session = ResearchShadowSession(
            market=market, decision_context=decision_context, cohort=cohort, task=task,
            symbol=symbol, trade_date=trade_date, frozen_at=frozen_at,
            market_snapshot_id=market_snapshot_id, market_snapshot_hash=market_snapshot_hash,
            coverage_ratio=coverage_ratio, event_coverage_status=event_coverage_status,
            provider_chain=provider_chain, model_artifact_hashes=model_artifact_hashes,
            frozen_prediction=prediction, prediction_price=prediction_price,
            candidate_predictions=candidate_predictions or {}, ensemble_weights=ensemble_weights or {},
            data_quality_mask=data_quality_mask or {}, event_missing_mask=event_missing_mask or {},
            provider_id=provider_id, revision_id=revision_id, source_delay_seconds=source_delay_seconds,
            evidence_coverage=evidence_coverage, model_disagreement=model_disagreement,
            influence_facts=influence_facts or [], abstained=bool(reasons),
            abstain_reasons=reasons, cache_state=cache_state,
            roster_hash=roster_hash, model_candidate=model_candidate,
            market_regime=market_regime,
            evidence_valid=(
                coverage_ratio >= 0.85 and cache_state not in {"expired", "unavailable"}
                and bool(model_artifact_hashes) and not provider_conflict
                and all(bool(value) for value in model_artifact_hashes.values())
            ),
        )
        return self.store.freeze(session)

    def backfill_prices(
        self, *, session: ResearchShadowSession, horizon_sessions: int,
        filled_at: datetime, closes: list[float], lows: list[float],
        entry_price: float | None = None,
        drawdown_entry_price: float | None = None,
        drawdown_lows: list[float] | None = None,
        suspended_during_window: bool = False, limit_event_during_window: bool = False,
    ) -> ResearchShadowOutcome:
        if horizon_sessions not in {1, 5, 20, 60}:
            raise ValueError("unsupported research shadow horizon")
        if (entry_price is None and session.prediction_price is None) or len(closes) < horizon_sessions or len(lows) < horizon_sessions:
            raise ValueError("research shadow outcome lacks a complete effective-trading-day window")
        entry = entry_price or session.prediction_price
        horizon_closes = closes[:horizon_sessions]
        horizon_lows = (drawdown_lows or lows)[:horizon_sessions]
        realized_return = horizon_closes[-1] / entry - 1
        path_returns = [value / entry - 1 for value in horizon_closes]
        drawdown_entry = drawdown_entry_price or entry
        low_returns = [value / drawdown_entry - 1 for value in horizon_lows]
        realized_drawdown = min(low_returns)
        direction = "up" if realized_return > 0.002 else "down" if realized_return < -0.002 else "flat"
        category, direction_brier, risk_brier, return_error = _score_outcome(
            session, direction=direction, realized_return=realized_return,
            realized_drawdown=realized_drawdown,
        )
        outcome = ResearchShadowOutcome(
            research_shadow_session_id=session.id, horizon_sessions=horizon_sessions,
            filled_at=filled_at, realized_return=realized_return,
            realized_max_drawdown=realized_drawdown, mae=min(low_returns),
            mfe=max(path_returns), direction=direction, data_complete=True,
            suspended_during_window=suspended_during_window,
            limit_event_during_window=limit_event_during_window,
            error_category=category, direction_brier_score=direction_brier,
            risk_brier_score=risk_brier, return_absolute_error=return_error,
        )
        return self.store.backfill(outcome)


def _score_outcome(
    session: ResearchShadowSession, *, direction: str,
    realized_return: float, realized_drawdown: float,
) -> tuple[str, float | None, float | None, float | None]:
    prediction = session.frozen_prediction
    if session.abstained:
        severe = abs(realized_return) > 0.05 or realized_drawdown <= -0.08
        return ("correct_abstain" if severe else "incorrect_abstain", None, None, None)
    if session.task.startswith("direction_"):
        probabilities = prediction.get("calibrated_probability", prediction)
        predicted = max(probabilities, key=probabilities.get)
        brier = sum((float(probabilities.get(label, 0.0)) - float(label == direction)) ** 2 for label in ("up", "down", "flat"))
        return ("correct" if predicted == direction else "direction_error", brier, None, None)
    if session.task == "return_20d":
        error = abs(realized_return - float(prediction.get("p50", 0.0)))
        inside = float(prediction.get("p10", float("-inf"))) <= realized_return <= float(prediction.get("p90", float("inf")))
        return ("correct" if inside else "direction_error", None, None, error)
    if session.task == "drawdown_20d":
        probability = float(prediction.get("calibrated_probability", 0.0))
        event = float(realized_drawdown <= -0.08)
        brier = (probability - event) ** 2
        predicted_high = probability >= 0.5
        return ("correct" if predicted_high == bool(event) else "risk_level_error", None, brier, None)
    return ("pending", None, None, None)


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None
