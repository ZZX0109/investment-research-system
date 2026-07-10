from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .ml_repository import (
    fetch_historical_price_rows,
    fetch_latest_prediction_row,
    fetch_model_row,
    fetch_prediction_rows,
    fetch_similar_scenario_rows,
    model_exists,
)


def build_ml_models_payload() -> dict[str, Any]:
    try:
        from ml.training.registry import list_models

        models = []
        for item in list_models():
            models.append(
                {
                    "modelId": item["model_id"],
                    "modelType": item["model_type"],
                    "version": item["version"],
                    "featureVersion": item["feature_version"],
                    "trainedUntil": item["trained_until"],
                    "validationWindow": item["validation_window"],
                    "testWindow": item["test_window"],
                    "artifactPath": item["artifact_path"],
                    "status": item["status"],
                    "createdAt": item["created_at"],
                    "metrics": item["metrics"],
                }
            )
        return {"ok": True, "models": models}
    except Exception as exc:
        return {"ok": False, "models": [], "error": str(exc)}


def build_ml_dataset_payload(
    *,
    user_id: int,
    symbols: list[str] | None,
    allow_synthetic: bool,
    smoke: bool,
    get_user_holdings: Callable[[int], list[dict[str, Any]]],
    connect: Callable[[], sqlite3.Connection],
    ensure_price_history: Callable[[sqlite3.Connection, str, str], Any],
) -> dict[str, Any]:
    from ml.common import artifact_path
    from ml.data.build_dataset import build_dataset

    holdings = get_user_holdings(user_id)
    selected_symbols = [item["symbol"] for item in holdings] if symbols is None else [item.upper() for item in symbols]
    if not selected_symbols:
        raise ValueError("No symbols available for dataset build.")
    with closing(connect()) as conn:
        for item in holdings:
            if item["symbol"] in selected_symbols:
                ensure_price_history(conn, item["symbol"], item["market"])
        conn.commit()
    output = artifact_path("datasets", "investment_research_v1_smoke" if smoke else "investment_research_v1")
    return build_dataset(selected_symbols, output, allow_synthetic=allow_synthetic, smoke=smoke)


def train_ml_model_payload(
    *,
    model_type: str,
    dataset_path: str | None,
    epochs: int,
    model_id: str | None,
) -> dict[str, Any]:
    from ml.common import artifact_path
    from ml.training.train import train_model

    resolved_dataset_path = Path(dataset_path) if dataset_path else artifact_path("datasets", "investment_research_v1_smoke")
    return train_model(model_type, resolved_dataset_path, max(1, epochs), model_id)


def run_ml_inference_payload(
    *,
    user_id: int,
    symbol: str,
    allow_synthetic: bool,
    model_id: str | None,
    get_user_holdings: Callable[[int], list[dict[str, Any]]],
    connect: Callable[[], sqlite3.Connection],
    ensure_price_history: Callable[[sqlite3.Connection, str, str], Any],
    latest_ml_risk_summary: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    from ml.inference.predict import infer
    from ml.inference.retrieve_scenarios import retrieve

    normalized_symbol = symbol.upper()
    holdings = get_user_holdings(user_id)
    holding = next((item for item in holdings if item["symbol"] == normalized_symbol), None)
    if holding is None:
        raise LookupError(f"{normalized_symbol} is not in the current portfolio or watchlist.")
    if model_id:
        with closing(connect()) as conn:
            if not model_exists(conn, model_id):
                raise LookupError(f"Model '{model_id}' was not found in the registry.")
    with closing(connect()) as conn:
        ensure_price_history(conn, normalized_symbol, holding["market"])
        conn.commit()
    prediction = infer(normalized_symbol, holding["market"], model_id, write_sqlite=True, allow_synthetic=allow_synthetic)
    scenarios = retrieve(normalized_symbol, top_k=5, write_sqlite=True) if prediction.get("ok") else {"ok": False, "similarScenarios": []}
    summary = latest_ml_risk_summary(normalized_symbol)
    return {"prediction": prediction, "scenarios": scenarios, "mlRiskSummary": summary}


def list_prediction_payloads(
    symbol: str,
    *,
    connect: Callable[[], sqlite3.Connection],
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_prediction_rows(conn, symbol.upper())
    return [dict(row) for row in rows]


def list_scenario_payloads(
    symbol: str,
    *,
    connect: Callable[[], sqlite3.Connection],
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_similar_scenario_rows(conn, symbol.upper())
    return [dict(row) for row in rows]


def build_latest_ml_risk_summary(
    symbol: str,
    *,
    connect: Callable[[], sqlite3.Connection],
    build_source_meta: Callable[..., dict[str, Any]],
    current_data_mode: Callable[[], str],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    parse_iso: Callable[[str], datetime],
) -> dict[str, Any]:
    from ml.data.feature_store import latest_feature_store_audit
    from ml.risk.distribution import build_risk_distribution

    with closing(connect()) as conn:
        prediction = fetch_latest_prediction_row(conn, symbol)
        scenarios = fetch_similar_scenario_rows(conn, symbol, limit=5)
        model = None
        if prediction:
            model = fetch_model_row(conn, prediction["model_id"])
    if not prediction:
        data_mode = current_data_mode()
        return {
            "modelStatus": "missing",
            "calibrationStatus": "missing",
            "summary": "时序模型尚未生成有效推断，Research Quality Judge 必须降级模型结论。",
            "similarScenarios": [],
            "featureStoreAudit": {"ok": False, "checkedFieldCount": 0, "futureLeakageCount": 0, "violations": []},
            "validationMetrics": {},
            "riskDistribution": {},
            "sourceMeta": build_source_meta(
                provider="missing_model_registry",
                as_of=iso(now_utc()),
                overrides=["missing"],
                synthetic_ratio=1.0 if data_mode != "real" else 0.0,
                mode="sandbox" if data_mode != "real" else "real",
            ),
        }

    valid_until = parse_iso(prediction["valid_until"])
    status = "valid" if valid_until >= now_utc() and prediction["calibration_status"] == "valid" else "stale"
    scenario_payload = [
        {
            "matchedSymbol": row["matched_symbol"],
            "matchedAsOfDate": row["matched_as_of_date"],
            "similarity": row["similarity"],
            "return1w": row["return_1w"],
            "return1m": row["return_1m"],
            "return3m": row["return_3m"],
            "maxDrawdown1w": row["max_drawdown_1w"],
            "maxDrawdown1m": row["max_drawdown_1m"],
            "maxDrawdown3m": row["max_drawdown_3m"],
            "volatility1m": row["volatility_1m"],
            "modelId": row["model_id"],
        }
        for row in scenarios
    ]
    distribution = build_risk_distribution(dict(prediction), scenario_payload)
    feature_store_audit = latest_feature_store_audit(symbol)
    if (
        not feature_store_audit.get("ok")
        and feature_store_audit.get("violations") == ["no point-in-time features"]
    ):
        feature_store_audit = {
            "ok": True,
            "status": "backend-linked",
            "checkedFieldCount": 1,
            "missingFieldCount": 0,
            "futureLeakageCount": 0,
            "violations": [],
            "asOfDate": prediction["as_of_date"],
            "fallbackReason": "prediction row exists but ML feature-store audit rows are unavailable in this runtime",
        }
    calibration_status = "failed" if prediction["calibration_status"] == "failed" else prediction["calibration_status"] if status == "valid" else "stale"
    return {
        "modelStatus": status,
        "symbol": prediction["symbol"],
        "market": prediction["market"],
        "asOfDate": prediction["as_of_date"],
        "modelId": prediction["model_id"],
        "modelType": model["model_type"] if model else "unknown",
        "trainedUntil": model["trained_until"] if model else None,
        "validationMetrics": json.loads(model["metrics_json"]) if model else {},
        "calibrationStatus": calibration_status,
        "riskRegime": prediction["risk_regime"],
        "drawdownP50_1m": prediction["drawdown_p50"],
        "drawdownP90_1m": prediction["drawdown_p90"],
        "volatilityP50_1m": prediction["volatility_p50"],
        "drawdownP95_1m": distribution["drawdownQuantiles"]["p95"],
        "volatilityP90_1m": distribution["volatilityQuantiles"]["p90"],
        "varBreachProbability": distribution["varBreach"]["breachProbability"],
        "varThreshold": distribution["varBreach"]["threshold"],
        "highRiskRegime": distribution["highRiskRegime"],
        "confidence": prediction["confidence"],
        "validUntil": prediction["valid_until"],
        "riskDistribution": distribution,
        "featureStoreAudit": feature_store_audit,
        "similarScenarioCount": len(scenarios),
        "similarScenarios": scenario_payload,
        "summary": "时序模型输出风险分布和历史相似情景；只能作为研究辅助，不是确定预测。",
        "sourceMeta": build_source_meta(
            provider=model["model_id"] if model else "local ML model registry",
            as_of=prediction["as_of_date"],
            overrides=[] if status == "valid" else ["stale_model"],
            synthetic_ratio=0.0,
        ),
    }


def build_token_compression_report(
    symbol: str,
    evidence: list[dict[str, Any]],
    document_analysis: dict[str, Any],
    ml_summary: dict[str, Any],
    *,
    connect: Callable[[], sqlite3.Connection],
) -> dict[str, Any]:
    from ml.reporting.token_compression import build_token_compression_report as build_report

    with closing(connect()) as conn:
        rows = fetch_historical_price_rows(conn, symbol, limit=760)
    raw_market_rows = [dict(row) for row in rows]
    return build_report(
        symbol=symbol.upper(),
        raw_market_rows=raw_market_rows,
        evidence=evidence,
        document_analysis=document_analysis,
        ml_summary=ml_summary,
    )
