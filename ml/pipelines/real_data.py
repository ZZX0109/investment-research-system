from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ml.common import artifact_path, write_json
from ml.data.build_dataset import build_dataset
from ml.data.ingest_history import ensure_history, purge_synthetic_history
from ml.data.quality import dataset_quality_report
from ml.inference.predict import infer
from ml.inference.retrieve_scenarios import retrieve
from ml.pipelines.common import REAL_V1_SYMBOLS, dataset_gates, dataset_stats, deep_candidate_audit, metric_gates, parse_symbols, symbol_market, write_manifest, write_model_card
from ml.training.train import train_model


def real_data_gates(stats: dict[str, Any], metrics: dict[str, Any], quality: dict[str, Any], *, min_symbols: int, min_samples: int) -> list[dict[str, Any]]:
    coverage = quality.get("coverage", {})
    return [
        *dataset_gates(stats, min_symbols=min_symbols, min_samples=min_samples),
        *metric_gates(metrics, strict=True),
        {
            "name": "real_only_samples",
            "passed": stats.get("sourceStatus", {}).get("degraded", 0) == 0,
            "value": stats.get("sourceStatus"),
            "limit": "no degraded/synthetic samples",
        },
        {
            "name": "adjusted_price_coverage",
            "passed": coverage.get("adjustedPrices", {}).get("passedCount", 0) >= min_symbols,
            "value": coverage.get("adjustedPrices"),
            "limit": f">={min_symbols}",
        },
        {
            "name": "revision_history_available",
            "passed": coverage.get("revisionHistory", {}).get("passedCount", 0) >= min_symbols,
            "value": coverage.get("revisionHistory"),
            "limit": f">={min_symbols}",
        },
        {
            "name": "survivorship_bias_disclosed",
            "passed": coverage.get("survivorshipBiasDisclosure", {}).get("passedCount", 0) >= min_symbols,
            "value": coverage.get("survivorshipBiasDisclosure"),
            "limit": f">={min_symbols}",
        },
    ]


def write_real_readiness_report(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    quality = payload["qualityReport"]
    report = {
        "runId": run_id,
        "readiness": "pass" if payload["ok"] else "fail",
        "modelId": payload["model"]["modelId"],
        "dataset": payload["datasetStats"],
        "syntheticPurge": payload.get("syntheticPurge"),
        "qualityCoverage": quality["coverage"],
        "gateFailures": [item for item in payload["gates"] if not item["passed"]],
        "nextScaleStep": {
            "targetUsEtfSymbols": "100-300",
            "targetCnFundSymbols": "100-300",
            "dailyHistory": "5-8 years",
            "models": ["tabular_baseline", "cnn_tcn", "patch_tst_lite_or_itransformer_lite", "scenario_encoder"],
        },
    }
    write_json(artifact_path("pipelines", run_id, "real_readiness_report.json"), report)
    return report


def run_real_data_v1(
    *,
    symbols: list[str] | None = None,
    model_id: str = "risk_tabular_real_v1",
    smoke: bool = False,
    max_symbols: int | None = None,
    min_symbols: int = 20,
    min_samples: int = 800,
    min_rows: int = 1000,
    max_samples_per_symbol: int | None = None,
    compact_feature_metadata: bool = False,
    window_mode: str = "none",
    train_deep: bool = False,
    require_deep_pass: bool = False,
) -> dict[str, Any]:
    selected = symbols or REAL_V1_SYMBOLS
    if max_symbols:
        selected = selected[:max_symbols]
    ingest = [
        ensure_history(
            symbol,
            symbol_market(symbol),
            min_rows=min_rows,
            fetch_real=True,
            allow_synthetic=False,
            real_only=True,
        )
        for symbol in selected
    ]
    usable_symbols = [item["symbol"] for item in ingest if item["ok"]]
    synthetic_purge = {
        "deletedRows": sum(purge_synthetic_history(symbol) for symbol in usable_symbols),
        "symbols": usable_symbols,
    }
    effective_window_mode = "window120" if train_deep and window_mode == "none" else window_mode
    dataset_path = artifact_path("datasets", "real_data_v1")
    dataset = build_dataset(
        usable_symbols,
        dataset_path,
        allow_synthetic=False,
        smoke=smoke,
        max_samples_per_symbol=max_samples_per_symbol,
        compact_feature_metadata=compact_feature_metadata,
        window_mode=effective_window_mode,
    )
    trained = train_model("tabular_baseline", Path(dataset["datasetPath"]), epochs=1, model_id=model_id)

    deep_candidates: list[dict[str, Any]] = []
    if train_deep:
        for model_type in ["cnn_tcn", "patch_tst_lite", "itransformer_lite"]:
            deep_candidates.append(train_model(model_type, Path(dataset["datasetPath"]), epochs=1, model_id=f"{model_type}_real_candidate_v1"))
    deep_audit = deep_candidate_audit(deep_candidates)

    inference_results = []
    for index, symbol in enumerate(usable_symbols):
        prediction = infer(symbol, symbol_market(symbol), model_id=model_id, write_sqlite=True, allow_synthetic=False)
        scenarios = retrieve(symbol, top_k=5, write_sqlite=True) if prediction.get("ok") and index < 8 else {"ok": bool(prediction.get("ok")), "similarScenarios": []}
        if index < 8:
            inference_results.append(
                {
                    "symbol": symbol,
                    "ok": bool(prediction.get("ok")),
                    "riskRegime": prediction.get("riskDistribution", {}).get("riskRegime"),
                    "calibrationStatus": prediction.get("calibrationStatus"),
                    "scenarioCount": len(scenarios.get("similarScenarios", [])),
                }
            )

    stats = dataset_stats(Path(dataset["datasetPath"]))
    quality = dataset_quality_report(
        usable_symbols,
        universe_name="real_data_v1_20_50_liquid_us_equity_etf",
        survivorship_note="Initial real_data_v1 uses a current liquid large-cap/ETF universe; production scale must add date-stamped universe membership snapshots to reduce survivorship bias.",
    )
    gates = [
        *real_data_gates(stats, trained["metrics"], quality, min_symbols=min_symbols, min_samples=min_samples),
        {
            "name": "inference_preview_ok",
            "passed": all(item["ok"] for item in inference_results) and bool(inference_results),
            "value": inference_results,
            "limit": "all preview symbols",
        },
    ]
    if require_deep_pass:
        gates.append(
            {
                "name": "deep_candidate_audit_pass",
                "passed": deep_audit["status"] == "pass",
                "value": deep_audit["status"],
                "limit": "pass",
            }
        )
    model_card = write_model_card(
        pipeline="real_data_v1",
        model_id=model_id,
        dataset={**stats, "qualityCoverage": quality["coverage"]},
        trained=trained,
        gates=gates,
        inference=inference_results,
    )
    payload = {
        "ok": all(item["passed"] for item in gates),
        "stage": "real_data_v1",
        "symbolsRequested": selected,
        "usableSymbols": usable_symbols,
        "syntheticPurge": synthetic_purge,
        "ingest": ingest,
        "dataset": dataset,
        "datasetStats": stats,
        "qualityReport": quality,
        "model": {"modelId": model_id, "artifactPath": trained["artifactPath"], "modelCard": f"artifacts/models/{model_id}/model_card.json"},
        "deepCandidates": deep_candidates,
        "deepCandidateAudit": deep_audit,
        "gates": gates,
        "modelCard": model_card,
    }
    readiness = write_real_readiness_report("real_data_v1", payload)
    return write_manifest("real_data_v1", {**payload, "realReadinessReport": readiness})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--model-id", default="risk_tabular_real_v1")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--min-symbols", type=int, default=20)
    parser.add_argument("--min-samples", type=int, default=800)
    parser.add_argument("--min-rows", type=int, default=1000)
    parser.add_argument("--max-samples-per-symbol", type=int, default=None)
    parser.add_argument("--compact-feature-metadata", action="store_true")
    parser.add_argument("--window-mode", choices=["full", "window120", "none"], default="none")
    parser.add_argument("--train-deep", action="store_true")
    parser.add_argument("--require-deep-pass", action="store_true")
    args = parser.parse_args()
    result = run_real_data_v1(
        symbols=parse_symbols(args.symbols, REAL_V1_SYMBOLS),
        model_id=args.model_id,
        smoke=args.smoke,
        max_symbols=args.max_symbols,
        min_symbols=args.min_symbols,
        min_samples=args.min_samples,
        min_rows=args.min_rows,
        max_samples_per_symbol=args.max_samples_per_symbol,
        compact_feature_metadata=args.compact_feature_metadata,
        window_mode=args.window_mode,
        train_deep=args.train_deep,
        require_deep_pass=args.require_deep_pass,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
