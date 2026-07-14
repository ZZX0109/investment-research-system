from __future__ import annotations

import math
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from investment_research.domain.decision_context import EXCHANGE_SESSIONS

from investment_research.repository.sqlite import SQLiteUnitOfWork


class PaperValidationWorker:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def tick(self, as_of: datetime | None = None) -> dict[str, int]:
        now = as_of or datetime.now(timezone.utc)
        observations = self.evaluate_observations(now)
        evaluated = self.evaluate_due(now)
        drift = self.generate_previous_month_drift(now)
        return {"evaluated": evaluated + observations, "drift_reports": drift}

    def evaluate_observations(self, now: datetime) -> int:
        """Settle the user-visible fixed-run observations without touching predictions."""
        updated = 0
        for item in self.uow.paper_observations.list_pending():
            asset = self.uow.assets.get(str(item.asset_id))
            zone = ZoneInfo(EXCHANGE_SESSIONS[_calendar_code(asset)].timezone)
            eligible = [
                point
                for series in self.uow.price_series.list_for_asset(str(item.asset_id))
                if series.interval == "1d" and series.series_role in {None, "asset"}
                for point in series.points
                if point.timestamp >= item.prediction_as_of
            ]
            # One authoritative close per exchange-local trading date; intraday quotes never advance the horizon.
            by_day = {}
            for point in sorted(eligible, key=lambda value: value.timestamp):
                by_day[point.timestamp.astimezone(zone).date()] = point
            points = list(by_day.values())
            if not points:
                continue
            closes = [float(point.close) for point in points]
            latest = closes[-1]
            prediction_price = item.prediction_price or closes[0]
            drawdown = self._max_drawdown(closes)
            due = len(points) >= item.horizon_days
            outcome = (
                "pending"
                if not due
                else (
                    "risk_hit"
                    if self._max_drawdown(closes[: item.horizon_days]) <= -0.08
                    else "risk_miss"
                )
            )
            milestones = dict(item.milestones)
            for horizon in (1, 5, 20, 60):
                key = str(horizon)
                if len(points) >= horizon and key not in milestones:
                    milestone_closes = closes[:horizon]
                    realized_return = (
                        milestone_closes[-1]
                        / (item.prediction_price or milestone_closes[0])
                        - 1.0
                    )
                    milestone_points = points[:horizon]
                    base = item.prediction_price or milestone_closes[0]
                    low_returns = [
                        float(value.low) / base - 1.0 for value in milestone_points
                    ]
                    high_returns = [
                        float(value.high) / base - 1.0 for value in milestone_points
                    ]
                    from investment_research.domain.models import ObservationMilestone

                    milestones[key] = ObservationMilestone(
                        horizon_days=horizon,
                        evaluated_at=now,
                        realized_return=realized_return,
                        realized_max_drawdown=self._max_drawdown_intraday(
                            milestone_points, base
                        ),
                        maximum_adverse_excursion=min(low_returns),
                        maximum_favorable_excursion=max(high_returns),
                        realized_direction="up"
                        if realized_return >= 0.02
                        else "down"
                        if realized_return <= -0.02
                        else "flat",
                    )
            final = len(points) >= 60
            category = self._error_category(item, milestones, outcome)
            self.uow.paper_observations.add(
                item.model_copy(
                    update={
                        "prediction_price": prediction_price,
                        "latest_price": latest,
                        "cumulative_return": latest / prediction_price - 1
                        if prediction_price
                        else None,
                        "realized_max_drawdown": drawdown,
                        "observed_trading_days": len(points),
                        "outcome": outcome,
                        "state": "evaluated" if final else "pending",
                        "evaluated_at": now if final else None,
                        "settlement_source": "persisted-real-price-series",
                        "milestones": milestones,
                        "error_category": category,
                    }
                )
            )
            updated += 1
        return updated

    @staticmethod
    def _error_category(item, milestones, outcome: str) -> str:
        if not milestones:
            return "pending"
        if any(
            "synthetic" in reason or "data" in reason for reason in item.abstain_reasons
        ):
            return "data_error"
        milestone_20 = milestones.get("20")
        if item.abstained and milestone_20 is not None:
            return (
                "correct_abstain"
                if milestone_20.realized_max_drawdown <= -0.08
                else "incorrect_abstain"
            )
        direction = item.frozen_probabilities.get("direction_5d")
        milestone_5 = milestones.get("5")
        if isinstance(direction, dict) and milestone_5 is not None:
            predicted = max(
                ("up", "down", "flat"), key=lambda key: float(direction.get(key, 0.0))
            )
            if predicted != milestone_5.realized_direction:
                return "direction_error"
        if milestone_20 is not None and item.predicted_risk is not None:
            predicted_hit = item.predicted_risk >= 0.5
            actual_hit = outcome == "risk_hit"
            if predicted_hit != actual_hit:
                return "risk_level_error"
            return "correct"
        return "pending"

    def evaluate_due(self, now: datetime) -> int:
        count = 0
        for prediction in self.uow.agent_runtime.due_paper_predictions(now):
            prediction_as_of = datetime.fromisoformat(str(prediction["as_of"]))
            points = sorted(
                [
                    point
                    for series in self.uow.price_series.list_for_asset(
                        str(prediction["asset_id"])
                    )
                    if series.series_role == "asset" and series.interval == "1d"
                    for point in series.points
                    if point.timestamp > prediction_as_of
                ],
                key=lambda item: item.timestamp,
            )
            by_day = {}
            asset = self.uow.assets.get(str(prediction["asset_id"]))
            zone = ZoneInfo(EXCHANGE_SESSIONS[_calendar_code(asset)].timezone)
            for point in points:
                by_day[point.timestamp.astimezone(zone).date()] = point
            daily_points = list(by_day.values())
            if len(daily_points) < 20:
                continue
            closes = [float(point.close) for point in daily_points[:20]]
            realized = self._max_drawdown(closes)
            lead = self._alert_lead_days(closes)
            self.uow.agent_runtime.add_paper_outcome(
                prediction_id=str(prediction["id"]),
                realized_max_drawdown=realized,
                alert_lead_days=lead,
                evaluated_at=now,
            )
            count += 1
        return count

    def generate_previous_month_drift(self, now: datetime) -> int:
        period_end = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        if period_end.month == 1:
            period_start = datetime(period_end.year - 1, 12, 1, tzinfo=timezone.utc)
        else:
            period_start = datetime(
                period_end.year, period_end.month - 1, 1, tzinfo=timezone.utc
            )
        grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
        for row in self.uow.agent_runtime.evaluated_paper_rows(
            period_start, period_end
        ):
            grouped[str(row["model_id"])].append(row)
        generated = 0
        for model_id, rows in grouped.items():
            if self.uow.agent_runtime.drift_exists(model_id, period_start, period_end):
                continue
            valid = [
                row
                for row in rows
                if row["risk_probability"] is not None and not bool(row["abstained"])
            ]
            labels = [
                1.0 if float(row["realized_max_drawdown"]) <= -0.08 else 0.0
                for row in valid
            ]
            probabilities = [float(row["risk_probability"]) for row in valid]
            brier = (
                None
                if not valid
                else sum(
                    (probability - label) ** 2
                    for probability, label in zip(probabilities, labels)
                )
                / len(valid)
            )
            ece = self._ece(probabilities, labels)
            top = [
                float(row["realized_max_drawdown"])
                for row in valid
                if float(row["risk_probability"]) >= 0.8
            ]
            all_drawdowns = [float(row["realized_max_drawdown"]) for row in valid]
            lift = (
                None
                if not top or not all_drawdowns
                else (sum(all_drawdowns) / len(all_drawdowns)) - (sum(top) / len(top))
            )
            coverage = sum(float(row["feature_coverage"]) for row in rows) / len(rows)
            abstention = sum(bool(row["abstained"]) for row in rows) / len(rows)
            provider_missing = sum(
                float(row["provider_missing_rate"]) for row in rows
            ) / len(rows)
            psi = self._feature_psi(rows)
            verdict = (
                "hold"
                if (ece is not None and ece > 0.15)
                or (psi is not None and psi > 0.25)
                or (lift is not None and lift <= 0)
                else "pass"
            )
            self.uow.agent_runtime.add_drift_evaluation(
                period_start=period_start,
                period_end=period_end,
                model_id=model_id,
                psi=psi,
                ece=ece,
                brier=brier,
                drawdown_lift=lift,
                feature_coverage=coverage,
                abstention_rate=abstention,
                provider_missing_rate=provider_missing,
                verdict=verdict,
            )
            generated += 1
        return generated

    @staticmethod
    def _max_drawdown_intraday(points, entry_price: float) -> float:
        peak = entry_price
        worst = 0.0
        for point in points:
            peak = max(peak, float(point.high))
            worst = min(worst, (float(point.low) / peak) - 1.0)
        return worst

    @staticmethod
    def _max_drawdown(closes: list[float]) -> float:
        peak = closes[0]
        worst = 0.0
        for value in closes:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1.0)
        return worst

    @staticmethod
    def _alert_lead_days(closes: list[float]) -> int | None:
        peak = closes[0]
        for index, value in enumerate(closes):
            peak = max(peak, value)
            if value / peak - 1.0 <= -0.08:
                return index
        return None

    @staticmethod
    def _ece(
        probabilities: list[float], labels: list[float], bins: int = 10
    ) -> float | None:
        if not probabilities:
            return None
        total = len(probabilities)
        error = 0.0
        for bucket in range(bins):
            lower, upper = bucket / bins, (bucket + 1) / bins
            indexes = [
                index
                for index, value in enumerate(probabilities)
                if lower <= value < upper
                or (bucket == bins - 1 and math.isclose(value, 1.0))
            ]
            if not indexes:
                continue
            confidence = sum(probabilities[index] for index in indexes) / len(indexes)
            observed = sum(labels[index] for index in indexes) / len(indexes)
            error += len(indexes) / total * abs(confidence - observed)
        return error

    @staticmethod
    def _feature_psi(rows: list[dict[str, object]]) -> float | None:
        vectors = [
            json.loads(str(row["feature_values_json"]))
            for row in rows
            if row.get("feature_values_json")
        ]
        if len(vectors) < 5:
            return None
        scaler_path = (
            Path(__file__).resolve().parents[3] / "output/models/scaler_params.json"
        )
        if not scaler_path.exists():
            return None
        scaler = json.loads(scaler_path.read_text(encoding="utf-8"))
        means = scaler.get("mean", [])
        scales = scaler.get("scale", [])
        if not means or len(means) != len(vectors[0]) or len(scales) != len(vectors[0]):
            return None
        boundaries = [-math.inf, -2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0, math.inf]

        def normal_cdf(value: float) -> float:
            if value == -math.inf:
                return 0.0
            if value == math.inf:
                return 1.0
            return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))

        expected = [
            normal_cdf(right) - normal_cdf(left)
            for left, right in zip(boundaries, boundaries[1:])
        ]
        feature_scores = []
        for index, (mean, scale) in enumerate(zip(means, scales)):
            denominator = float(scale) or 1.0
            values = [
                (float(vector[index]) - float(mean)) / denominator for vector in vectors
            ]
            score = 0.0
            for bin_index, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
                actual = sum(left <= value < right for value in values) / len(values)
                actual = max(actual, 1e-6)
                reference = max(expected[bin_index], 1e-6)
                score += (actual - reference) * math.log(actual / reference)
            feature_scores.append(score)
        return sum(feature_scores) / len(feature_scores)


def _calendar_code(asset) -> str:
    if asset is None:
        return "XSHG"
    exchange = (asset.exchange or "").upper()
    if exchange in EXCHANGE_SESSIONS:
        return exchange
    ticker = asset.ticker.upper()
    if ticker.endswith(".HK"):
        return "XHKG"
    if ticker.endswith(".T"):
        return "XTKS"
    if ticker.endswith(".SH"):
        return "XSHG"
    if ticker.endswith(".SZ"):
        return "XSHE"
    if ticker.endswith(".BJ"):
        return "XBSE"
    return "XNYS"
