from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ml.common import FEATURE_VERSION, connect, now_iso
from ml.data.build_dataset import DEFAULT_SYMBOL_MARKETS, load_history
from ml.data.feature_store import build_feature_metadata, persist_feature_record, validate_feature_metadata
from ml.features.market import FEATURE_NAMES, tabular_snapshot, window_features
from ml.models.tabular_baseline import load_model, predict_tabular
from ml.risk.distribution import build_risk_distribution
from ml.training.registry import ensure_ml_schema, latest_approved_model, list_models


def latest_model(model_id: str | None = None) -> dict[str, Any] | None:
    ensure_ml_schema()
    if model_id:
        for model in list_models():
            if model["model_id"] == model_id:
                return model
        return None
    return latest_approved_model()


def build_latest_features(symbol: str, market: str, allow_synthetic: bool = False) -> dict[str, Any] | None:
    rows = load_history(symbol, allow_synthetic=allow_synthetic)
    if len(rows) < 120:
        return None
    closes = [float(row["close_price"]) for row in rows]
    volumes = [float(row["volume"]) for row in rows]
    dates = [str(row["trade_date"]) for row in rows]
    source_names = [str(row["source_name"]) for row in rows]
    index = len(rows) - 1
    source_status = "degraded" if any("synthetic" in str(row["source_name"]).lower() for row in rows) else "live"
    field_metadata = build_feature_metadata(
        as_of_date=str(rows[index]["trade_date"]),
        source=", ".join(sorted(set(source_names))),
        dates=dates,
        sources=source_names,
        tabular_field_count=len(FEATURE_NAMES),
        windows={"window120": 120},
    )
    return {
        "symbol": symbol,
        "market": market,
        "asOfDate": str(rows[index]["trade_date"]),
        "featureVersion": FEATURE_VERSION,
        "featureNames": FEATURE_NAMES,
        "tabular": tabular_snapshot(closes, volumes, index),
        "window120": window_features(closes, volumes, index, 120),
        "sourceStatus": source_status,
        "fieldMetadata": field_metadata,
        "pointInTimeAudit": validate_feature_metadata(field_metadata),
    }


def heuristic_prediction(features: list[float]) -> dict[str, Any]:
    ret_21 = features[2] if len(features) > 2 else 0
    vol_21 = features[5] if len(features) > 5 else 0.3
    drawdown = features[7] if len(features) > 7 else -0.05
    if ret_21 < -0.08 or vol_21 > 0.45 or drawdown < -0.12:
        regime = "high"
        confidence = 0.58
    elif ret_21 < -0.03 or vol_21 > 0.32 or drawdown < -0.06:
        regime = "medium"
        confidence = 0.55
    else:
        regime = "low"
        confidence = 0.52
    return {
        "riskRegime": regime,
        "drawdownP50": round(min(-0.01, drawdown), 4),
        "drawdownP90": round(min(-0.03, drawdown * 1.8), 4),
        "volatilityP50": round(max(0.05, vol_21), 4),
        "confidence": confidence,
    }


def infer(symbol: str, market: str | None = None, model_id: str | None = None, write_sqlite: bool = True, allow_synthetic: bool = False) -> dict[str, Any]:
    symbol = symbol.upper()
    market = market or DEFAULT_SYMBOL_MARKETS.get(symbol, "us")
    model = latest_model(model_id)
    features = build_latest_features(symbol, market, allow_synthetic=allow_synthetic)
    if not model or not features:
        return {
            "ok": False,
            "modelStatus": "missing",
            "calibrationStatus": "missing",
            "symbol": symbol,
            "market": market,
            "reason": "No approved model or insufficient feature history.",
        }
    artifact = Path(model["artifact_path"])
    if model["model_type"] == "tabular_baseline" and artifact.exists():
        prediction = predict_tabular(load_model(artifact), features["tabular"])
    else:
        prediction = heuristic_prediction(features["tabular"])
    valid_until = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    status = "stale" if features["sourceStatus"] == "degraded" else "valid"
    metrics = model.get("metrics", {})
    calibrated = float(metrics.get("calibration_ece", 1.0)) <= 0.12 and float(metrics.get("pinball_loss", 1.0)) <= 0.2
    calibration_status = "failed" if not calibrated else "valid" if status == "valid" else "stale"
    risk_distribution = build_risk_distribution(prediction, [])
    payload = {
        "ok": True,
        "modelStatus": "valid" if status == "valid" else "stale",
        "symbol": symbol,
        "market": market,
        "asOfDate": features["asOfDate"],
        "modelId": model["model_id"],
        "modelType": model["model_type"],
        "trainedUntil": model["trained_until"],
        "calibrationStatus": calibration_status,
        "validationMetrics": metrics,
        "riskDistribution": {
            **risk_distribution,
            "pointEstimate": {
                "riskRegime": prediction["riskRegime"],
                "drawdownP50": prediction["drawdownP50"],
                "drawdownP90": prediction["drawdownP90"],
                "volatilityP50": prediction["volatilityP50"],
                "confidence": prediction["confidence"],
            },
        },
        "localSignals": local_signals(features["tabular"]),
        "featureSnapshot": features,
        "validUntil": valid_until,
    }
    if write_sqlite:
        write_prediction(payload)
    return payload


def local_signals(features: list[float]) -> list[str]:
    signals: list[str] = []
    if len(features) > 10 and abs(features[9]) > 1.8:
        signals.append("volume_spike")
    if len(features) > 11 and features[11] > 0.04:
        signals.append("price_acceleration")
    if len(features) > 5 and features[5] > 0.4:
        signals.append("volatility_breakout")
    return signals or ["no_extreme_local_signal"]


def write_prediction(payload: dict[str, Any]) -> None:
    ensure_ml_schema()
    snapshot = payload["featureSnapshot"]
    created_at = now_iso()
    pit_audit = persist_feature_record(payload["symbol"], payload["market"], payload["asOfDate"], snapshot, snapshot["fieldMetadata"])
    with connect() as conn:
        conn.execute(
            """
            insert or replace into feature_snapshots(symbol, market, as_of_date, feature_version, features_json, source_status_json, created_at)
            values(?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["symbol"],
                payload["market"],
                payload["asOfDate"],
                snapshot["featureVersion"],
                json.dumps(
                    {
                        "featureNames": snapshot["featureNames"],
                        "tabular": snapshot["tabular"],
                        "window120": snapshot["window120"],
                        "fieldMetadata": snapshot["fieldMetadata"],
                        "pointInTimeAudit": pit_audit,
                    },
                    ensure_ascii=False,
                ),
                json.dumps({"sourceStatus": snapshot["sourceStatus"], "pointInTimeAudit": pit_audit}, ensure_ascii=False),
                created_at,
            ),
        )
        risk = payload["riskDistribution"]
        point = risk.get("pointEstimate", {})
        conn.execute(
            """
            insert into risk_predictions(symbol, market, as_of_date, model_id, horizon, risk_regime, drawdown_p50, drawdown_p90, volatility_p50, confidence, calibration_status, valid_until, created_at)
            values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["symbol"],
                payload["market"],
                payload["asOfDate"],
                payload["modelId"],
                risk["horizon"],
                point.get("riskRegime", risk["riskRegime"]),
                point.get("drawdownP50", risk["drawdownQuantiles"]["p50"]),
                point.get("drawdownP90", risk["drawdownQuantiles"]["p90"]),
                point.get("volatilityP50", risk["volatilityQuantiles"]["p50"]),
                point.get("confidence", 0.5),
                payload["calibrationStatus"],
                payload["validUntil"],
                created_at,
            ),
        )
        conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--market", default=None)
    parser.add_argument("--model-id", default=None)
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--write-sqlite", action="store_true")
    args = parser.parse_args()
    print(json.dumps(infer(args.symbol, args.market, args.model_id, args.write_sqlite, args.allow_synthetic), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
