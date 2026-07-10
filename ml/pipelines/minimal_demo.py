from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ml.common import artifact_path
from ml.data.build_dataset import build_dataset
from ml.data.ingest_history import ensure_history
from ml.inference.predict import infer
from ml.inference.retrieve_scenarios import retrieve
from ml.pipelines.common import MINIMAL_SYMBOLS, dataset_gates, dataset_stats, metric_gates, parse_symbols, symbol_market, write_manifest, write_model_card
from ml.training.train import train_model


def run_minimal_demo(
    *,
    symbols: list[str] | None = None,
    model_id: str = "risk_tabular_min_v1",
    allow_synthetic: bool = False,
    fetch_real: bool = False,
    smoke: bool = True,
) -> dict[str, Any]:
    selected = symbols or MINIMAL_SYMBOLS
    ingest = [
        ensure_history(symbol, symbol_market(symbol), min_rows=260, fetch_real=fetch_real, allow_synthetic=allow_synthetic, synthetic_days=980)
        for symbol in selected
    ]
    dataset_path = artifact_path("datasets", "minimal_demo_v1")
    dataset = build_dataset(selected, dataset_path, allow_synthetic=allow_synthetic, smoke=smoke)
    trained = train_model("tabular_baseline", Path(dataset["datasetPath"]), epochs=1, model_id=model_id)
    inference_results = []
    for symbol in selected[: min(4, len(selected))]:
        prediction = infer(symbol, symbol_market(symbol), model_id=model_id, write_sqlite=True, allow_synthetic=allow_synthetic)
        scenarios = retrieve(symbol, top_k=5, write_sqlite=True) if prediction.get("ok") else {"ok": False, "similarScenarios": []}
        inference_results.append(
            {
                "symbol": symbol,
                "ok": bool(prediction.get("ok")),
                "modelStatus": prediction.get("modelStatus"),
                "calibrationStatus": prediction.get("calibrationStatus"),
                "scenarioCount": len(scenarios.get("similarScenarios", [])),
            }
        )
    stats = dataset_stats(Path(dataset["datasetPath"]))
    gates = [
        *dataset_gates(stats, min_symbols=min(4, len(selected)), min_samples=24),
        *metric_gates(trained["metrics"], strict=False),
        {"name": "inference_preview_ok", "passed": all(item["ok"] for item in inference_results), "value": inference_results, "limit": "all preview symbols"},
    ]
    model_card = write_model_card(
        pipeline="minimal_demo",
        model_id=model_id,
        dataset=stats,
        trained=trained,
        gates=gates,
        inference=inference_results,
    )
    return write_manifest(
        "minimal_demo_v1",
        {
            "ok": all(item["passed"] for item in gates),
            "stage": "minimal_demo",
            "symbols": selected,
            "ingest": ingest,
            "dataset": dataset,
            "model": {"modelId": model_id, "artifactPath": trained["artifactPath"], "modelCard": f"artifacts/models/{model_id}/model_card.json"},
            "gates": gates,
            "modelCard": model_card,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--model-id", default="risk_tabular_min_v1")
    parser.add_argument("--allow-synthetic", action="store_true")
    parser.add_argument("--fetch-real", action="store_true")
    parser.add_argument("--full", action="store_true", help="Use all available samples instead of smoke sampling.")
    args = parser.parse_args()
    result = run_minimal_demo(
        symbols=parse_symbols(args.symbols, MINIMAL_SYMBOLS),
        model_id=args.model_id,
        allow_synthetic=args.allow_synthetic,
        fetch_real=args.fetch_real,
        smoke=not args.full,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
