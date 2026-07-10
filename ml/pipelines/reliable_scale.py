from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ml.common import artifact_path, read_json, write_json
from ml.data.build_dataset import build_dataset
from ml.data.feature_store import persist_feature_record
from ml.data.ingest_events import run_event_ingest
from ml.data.ingest_history import ensure_history, purge_synthetic_history
from ml.data.quality import dataset_quality_report
from ml.inference.predict import infer
from ml.inference.retrieve_scenarios import retrieve
from ml.pipelines.common import CN_SCALE_UNIVERSE_300, SCALED_SYMBOLS, US_SCALE_UNIVERSE_300, dataset_gates, dataset_stats, deep_candidate_audit, metric_gates, parse_symbols, symbol_market, write_manifest, write_model_card
from ml.training.train import train_model


def persist_latest_dataset_features(dataset_path: Path) -> dict[str, Any]:
    payload = read_json(dataset_path / "dataset.json")
    latest_by_symbol: dict[str, dict[str, Any]] = {}
    for sample in payload.get("samples", []):
        symbol = sample["symbol"]
        if symbol not in latest_by_symbol or sample["asOfDate"] > latest_by_symbol[symbol]["asOfDate"]:
            latest_by_symbol[symbol] = sample
    persisted = 0
    failures: list[dict[str, str]] = []
    for sample in latest_by_symbol.values():
        features = {
            "featureNames": sample.get("featureNames", []),
            "tabular": sample.get("tabular", []),
        }
        try:
            persist_feature_record(sample["symbol"], sample["market"], sample["asOfDate"], features, sample["fieldMetadata"])
            persisted += 1
        except Exception as exc:
            failures.append({"symbol": sample["symbol"], "reason": str(exc)[:240]})
    return {"persistedSymbolCount": persisted, "failureCount": len(failures), "failures": failures[:20]}


def reliability_gates(
    stats: dict[str, Any],
    metrics: dict[str, Any],
    *,
    min_symbols: int,
    min_samples: int,
    quality: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    gates = [
        *dataset_gates(stats, min_symbols=min_symbols, min_samples=min_samples),
        *metric_gates(metrics, strict=True),
        {
            "name": "walk_forward_has_multiple_windows",
            "passed": int(metrics.get("walk_forward", {}).get("windowCount") or 0) >= 2,
            "value": metrics.get("walk_forward", {}).get("windowCount"),
            "limit": ">=2",
        },
        {
            "name": "purged_cv_has_three_folds",
            "passed": int(metrics.get("purged_cv", {}).get("foldCount") or 0) >= 3,
            "value": metrics.get("purged_cv", {}).get("foldCount"),
            "limit": ">=3",
        },
    ]
    if quality:
        coverage = quality.get("coverage", {})
        gates.extend(
            [
                {
                    "name": "real_scale_no_synthetic_samples",
                    "passed": stats.get("sourceStatus", {}).get("degraded", 0) == 0,
                    "value": stats.get("sourceStatus"),
                    "limit": "no degraded/synthetic samples",
                },
                {
                    "name": "real_scale_adjusted_price_coverage",
                    "passed": coverage.get("adjustedPrices", {}).get("passedCount", 0) >= min_symbols,
                    "value": coverage.get("adjustedPrices"),
                    "limit": f">={min_symbols}",
                },
                {
                    "name": "real_scale_revision_history",
                    "passed": coverage.get("revisionHistory", {}).get("passedCount", 0) >= min_symbols,
                    "value": coverage.get("revisionHistory"),
                    "limit": f">={min_symbols}",
                },
                {
                    "name": "real_scale_survivorship_disclosure",
                    "passed": coverage.get("survivorshipBiasDisclosure", {}).get("passedCount", 0) >= min_symbols,
                    "value": coverage.get("survivorshipBiasDisclosure"),
                    "limit": f">={min_symbols}",
                },
            ]
        )
    return gates


def write_scale_readiness_report(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    report = {
        "runId": run_id,
        "readiness": "pass" if payload["ok"] else "fail",
        "datasetScale": payload["datasetStats"],
        "syntheticPurge": payload.get("syntheticPurge"),
        "featurePersistence": payload.get("featurePersistence"),
        "eventRefresh": payload.get("eventRefresh"),
        "qualityCoverage": payload.get("qualityReport", {}).get("coverage"),
        "deepCandidateAudit": payload.get("deepCandidateAudit"),
        "modelId": payload["model"]["modelId"],
        "requiredBeforeProduction": [
            "真实价格与复权数据覆盖目标市场。",
            "财报、公告、新闻事件全部带 availableAt 和 revisionId。",
            "加入 survivorship-bias universe 快照。",
            "对 CNN/Transformer 候选模型做同样的 walk-forward 与校准验证。",
            "建立人工复核 model card 签署流程。",
        ],
        "gateFailures": [item for item in payload["gates"] if not item["passed"]],
    }
    write_json(artifact_path("pipelines", run_id, "scale_readiness_report.json"), report)
    return report


def run_reliable_scale(
    *,
    symbols: list[str] | None = None,
    universe: str = "default",
    model_id: str = "risk_tabular_scale_v1",
    allow_synthetic: bool = False,
    fetch_real: bool = False,
    smoke: bool = False,
    max_symbols: int | None = None,
    min_symbols: int = 30,
    min_samples: int = 1200,
    min_rows: int = 1250,
    max_samples_per_symbol: int | None = None,
    compact_feature_metadata: bool = False,
    window_mode: str | None = None,
    refresh_events: bool = False,
    event_workers: int = 4,
    train_deep: bool = False,
    require_deep_pass: bool = False,
    ingest_workers: int = 1,
    run_id: str = "reliable_scale_v1",
    dataset_id: str = "reliable_scale_v1",
) -> dict[str, Any]:
    if symbols:
        selected = symbols
    elif universe == "large_us_cn":
        selected = list(dict.fromkeys([*US_SCALE_UNIVERSE_300[:300], *CN_SCALE_UNIVERSE_300[:300]]))
    else:
        selected = SCALED_SYMBOLS
    if max_symbols:
        selected = selected[:max_symbols]
    def ingest_symbol(symbol: str) -> dict[str, Any]:
        return ensure_history(
            symbol,
            symbol_market(symbol),
            min_rows=min_rows,
            fetch_real=fetch_real,
            allow_synthetic=allow_synthetic,
            synthetic_days=2300,
            real_only=fetch_real and not allow_synthetic,
        )

    if ingest_workers > 1:
        with ThreadPoolExecutor(max_workers=ingest_workers) as executor:
            ingest = list(executor.map(ingest_symbol, selected))
    else:
        ingest = [ingest_symbol(symbol) for symbol in selected]
    usable_symbols = [item["symbol"] for item in ingest if item["ok"]]
    synthetic_purge = (
        {"deletedRows": sum(purge_synthetic_history(symbol) for symbol in usable_symbols), "symbols": usable_symbols}
        if fetch_real and not allow_synthetic
        else {"deletedRows": 0, "symbols": []}
    )
    dataset_path = artifact_path("datasets", dataset_id)
    dataset = build_dataset(
        usable_symbols,
        dataset_path,
        allow_synthetic=allow_synthetic,
        smoke=smoke,
        max_samples_per_symbol=max_samples_per_symbol,
        compact_feature_metadata=compact_feature_metadata,
        window_mode=window_mode or ("window120" if train_deep else "none"),
    )
    feature_persistence = persist_latest_dataset_features(Path(dataset["datasetPath"]))
    trained = train_model("tabular_baseline", Path(dataset["datasetPath"]), epochs=1, model_id=model_id)
    deep_candidates: list[dict[str, Any]] = []
    if train_deep:
        for model_type in ["cnn_tcn", "patch_tst_lite", "itransformer_lite"]:
            deep_candidates.append(train_model(model_type, Path(dataset["datasetPath"]), epochs=1, model_id=f"{model_type}_scale_candidate_v1"))
    deep_audit = deep_candidate_audit(deep_candidates)
    event_refresh = run_event_ingest(usable_symbols, workers=event_workers) if refresh_events else {"ok": False, "skipped": True}

    inference_results = []
    for symbol in usable_symbols[: min(8, len(usable_symbols))]:
        prediction = infer(symbol, symbol_market(symbol), model_id=model_id, write_sqlite=True, allow_synthetic=allow_synthetic)
        scenarios = retrieve(symbol, top_k=5, write_sqlite=True) if prediction.get("ok") else {"ok": False, "similarScenarios": []}
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
    quality_report = (
        dataset_quality_report(
            usable_symbols,
            universe_name=f"reliable_scale_{universe}",
            survivorship_note="Scaled training uses a configured candidate universe at run time; production must replace this with date-stamped index/fund membership snapshots.",
        )
        if fetch_real and not allow_synthetic
        else {}
    )
    gates = [
        *reliability_gates(stats, trained["metrics"], min_symbols=min_symbols, min_samples=min_samples, quality=quality_report or None),
        {"name": "inference_preview_ok", "passed": all(item["ok"] for item in inference_results), "value": inference_results, "limit": "all preview symbols"},
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
        pipeline="reliable_scale",
        model_id=model_id,
        dataset=stats,
        trained=trained,
        gates=gates,
        inference=inference_results,
    )
    payload = {
        "ok": all(item["passed"] for item in gates),
        "stage": "reliable_scale",
        "symbolsRequested": selected,
        "usableSymbols": usable_symbols,
        "syntheticPurge": synthetic_purge,
        "ingest": ingest,
        "dataset": dataset,
        "datasetStats": stats,
        "featurePersistence": feature_persistence,
        "eventRefresh": event_refresh,
        "qualityReport": quality_report,
        "model": {"modelId": model_id, "artifactPath": trained["artifactPath"], "modelCard": f"artifacts/models/{model_id}/model_card.json"},
        "deepCandidates": deep_candidates,
        "deepCandidateAudit": deep_audit,
        "gates": gates,
        "modelCard": model_card,
    }
    readiness = write_scale_readiness_report(run_id, payload)
    return write_manifest(run_id, {**payload, "scaleReadinessReport": readiness})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--universe", choices=["default", "large_us_cn"], default="default")
    parser.add_argument("--model-id", default="risk_tabular_scale_v1")
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--fetch-real", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--min-symbols", type=int, default=30)
    parser.add_argument("--min-samples", type=int, default=1200)
    parser.add_argument("--min-rows", type=int, default=1250)
    parser.add_argument("--max-samples-per-symbol", type=int, default=None)
    parser.add_argument("--compact-feature-metadata", action="store_true")
    parser.add_argument("--window-mode", choices=["full", "window120", "none"], default=None)
    parser.add_argument("--refresh-events", action="store_true")
    parser.add_argument("--event-workers", type=int, default=4)
    parser.add_argument("--train-deep", action="store_true")
    parser.add_argument("--require-deep-pass", action="store_true")
    parser.add_argument("--ingest-workers", type=int, default=1)
    parser.add_argument("--run-id", default="reliable_scale_v1")
    parser.add_argument("--dataset-id", default="reliable_scale_v1")
    args = parser.parse_args()
    result = run_reliable_scale(
        symbols=parse_symbols(args.symbols, []) if args.symbols else None,
        universe=args.universe,
        model_id=args.model_id,
        allow_synthetic=args.allow_synthetic,
        fetch_real=args.fetch_real,
        smoke=args.smoke,
        max_symbols=args.max_symbols,
        min_symbols=args.min_symbols,
        min_samples=args.min_samples,
        min_rows=args.min_rows,
        max_samples_per_symbol=args.max_samples_per_symbol,
        compact_feature_metadata=args.compact_feature_metadata,
        window_mode=args.window_mode,
        refresh_events=args.refresh_events,
        event_workers=args.event_workers,
        train_deep=args.train_deep,
        require_deep_pass=args.require_deep_pass,
        ingest_workers=args.ingest_workers,
        run_id=args.run_id,
        dataset_id=args.dataset_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
