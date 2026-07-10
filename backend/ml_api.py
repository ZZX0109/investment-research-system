from __future__ import annotations

import sqlite3
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel


class MLDatasetBuildRequest(BaseModel):
    symbols: list[str] | None = None
    allowSynthetic: bool = False
    smoke: bool = False


class MLTrainRequest(BaseModel):
    modelType: str = "tabular_baseline"
    datasetPath: str | None = None
    epochs: int = 1
    modelId: str | None = None


class MLInferRequest(BaseModel):
    allowSynthetic: bool = False
    modelId: str | None = None


def build_ml_router(
    *,
    get_current_user: Callable[..., sqlite3.Row],
    ml_models_payload: Callable[[], dict[str, Any]],
    build_ml_dataset: Callable[[int, list[str] | None, bool, bool], dict[str, Any]],
    train_ml_model: Callable[[str, str | None, int, str | None], dict[str, Any]],
    run_ml_inference: Callable[[int, str, bool, str | None], dict[str, Any]],
    list_ml_predictions: Callable[[str], list[dict[str, Any]]],
    list_ml_scenarios: Callable[[str], list[dict[str, Any]]],
    get_user_holdings: Callable[[int], list[dict[str, Any]]],
    latest_ml_risk_summary: Callable[[str], dict[str, Any]],
    token_compression_report: Callable[[str, list[dict[str, Any]], dict[str, Any], dict[str, Any]], dict[str, Any]],
    get_evidence: Callable[[str], list[dict[str, Any]]],
    latest_document_analysis: Callable[[str], dict[str, Any]],
    api_source_meta: Callable[..., dict[str, Any]],
    data_mode_status: Callable[[], dict[str, Any]],
) -> APIRouter:
    router = APIRouter(tags=["ml"])

    @router.get("/api/ml/models")
    def ml_models(user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        payload = ml_models_payload()
        return {**payload, "dataMode": data_mode_status(), "sourceMeta": payload.get("sourceMeta") or api_source_meta("ml_model_registry")}

    @router.post("/api/ml/datasets/build")
    def ml_build_dataset(request: MLDatasetBuildRequest, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        user_id = int(user["id"])
        try:
            payload = build_ml_dataset(user_id, request.symbols, request.allowSynthetic, request.smoke)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            **payload,
            "dataMode": data_mode_status(),
            "sourceMeta": api_source_meta(
                "ml_dataset_builder",
                overrides=["synthetic"] if request.allowSynthetic else [],
                synthetic_ratio=1.0 if request.allowSynthetic else 0.0,
            ),
        }

    @router.post("/api/ml/train")
    def ml_train(request: MLTrainRequest, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        payload = train_ml_model(request.modelType, request.datasetPath, request.epochs, request.modelId)
        return {**payload, "dataMode": data_mode_status(), "sourceMeta": api_source_meta("ml_training_pipeline")}

    @router.post("/api/ml/infer/{symbol}")
    def ml_infer(symbol: str, request: MLInferRequest | None = None, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        request = request or MLInferRequest()
        symbol = symbol.upper()
        user_id = int(user["id"])
        try:
            payload = run_ml_inference(user_id, symbol, request.allowSynthetic, request.modelId)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        prediction = payload["prediction"]
        scenarios = payload["scenarios"]
        summary = payload["mlRiskSummary"]
        return {
            "ok": bool(prediction.get("ok")),
            "prediction": prediction,
            "scenarios": scenarios,
            "mlRiskSummary": summary,
            "dataMode": data_mode_status(),
            "sourceMeta": summary.get("sourceMeta") or api_source_meta("ml_inference_pipeline"),
        }

    @router.get("/api/ml/predictions/{symbol}")
    def ml_predictions(symbol: str, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        symbol = symbol.upper()
        summary = latest_ml_risk_summary(symbol)
        return {
            "symbol": symbol,
            "predictions": list_ml_predictions(symbol),
            "summary": summary,
            "dataMode": data_mode_status(),
            "sourceMeta": summary.get("sourceMeta") or api_source_meta("ml_predictions"),
        }

    @router.get("/api/ml/scenarios/{symbol}")
    def ml_scenarios(symbol: str, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        symbol = symbol.upper()
        return {
            "symbol": symbol,
            "scenarios": list_ml_scenarios(symbol),
            "dataMode": data_mode_status(),
            "sourceMeta": api_source_meta("ml_scenario_retrieval"),
        }

    @router.get("/api/ml/token-compression/{symbol}")
    def ml_token_compression(symbol: str, user: sqlite3.Row = Depends(get_current_user)) -> dict[str, Any]:
        symbol = symbol.upper()
        holdings = get_user_holdings(int(user["id"]))
        holding = next((item for item in holdings if item["symbol"] == symbol), None)
        if holding is None:
            raise HTTPException(status_code=404, detail=f"{symbol} is not in the current portfolio or watchlist.")
        evidence = get_evidence(symbol)
        document_analysis = latest_document_analysis(symbol)
        ml_summary = latest_ml_risk_summary(symbol)
        report = token_compression_report(symbol, evidence, document_analysis, ml_summary)
        return {
            "ok": True,
            "report": report,
            "dataMode": data_mode_status(),
            "sourceMeta": report.get("sourceMeta") or api_source_meta("ml_token_compression"),
        }

    return router
