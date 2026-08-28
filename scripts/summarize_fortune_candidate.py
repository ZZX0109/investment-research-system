#!/usr/bin/env python3
"""Create an auditable Fortune-candidate versus price-baseline comparison.

This is deliberately post-training: it reads only persisted manifests and
CatBoost model files, so selecting a candidate never needs to rerun a fold.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


HORIZONS = ("1d", "5d", "20d")
METRICS = ("directional_accuracy", "edge", "rank_ic", "sharpe_proxy", "max_drawdown_proxy")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _importance(model_path: Path, features: list[str]) -> list[dict[str, float | str]]:
    try:
        from catboost import CatBoostClassifier

        model = CatBoostClassifier()
        model.load_model(str(model_path))
        values = model.get_feature_importance()
        return [
            {"feature": str(name), "importance": float(value)}
            for name, value in sorted(zip(features, values), key=lambda item: item[1], reverse=True)
        ]
    except Exception as exc:
        return [{"feature": "unavailable", "importance": 0.0, "error": str(exc)}]


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    enhanced_root = root / "artifacts/short_term/fortune_enhanced"
    baseline_root = root / "artifacts/short_term/fortune_price_baseline"
    enhanced = _read(enhanced_root / "manifest.json")
    baseline = _read(baseline_root / "manifest.json")
    output: dict[str, Any] = {
        "schema_version": "fortune-candidate-comparison-v1",
        "enhanced_manifest": str(enhanced_root / "manifest.json"),
        "baseline_manifest": str(baseline_root / "manifest.json"),
        "horizons": {},
    }
    for horizon in HORIZONS:
        candidate = enhanced.get("horizons", {}).get(horizon, {}).get("aggregate", {})
        control = baseline.get("horizons", {}).get(horizon, {}).get("aggregate", {})
        delta = {key: float(candidate.get(key, 0.0)) - float(control.get(key, 0.0)) for key in METRICS}
        folds = enhanced.get("horizons", {}).get(horizon, {}).get("folds", [])
        rank_ic_wins = sum(1 for fold in folds if float(fold.get("rank_ic", 0.0)) > 0.0)
        output["horizons"][horizon] = {
            "enhanced": {key: candidate.get(key) for key in METRICS},
            "price_baseline": {key: control.get(key) for key in METRICS},
            "delta_enhanced_minus_baseline": delta,
            "positive_rank_ic_fold_count": rank_ic_wins,
            "fold_count": len(folds),
            "final_feature_importance_top20": _importance(enhanced_root / f"fortune_enhanced_{horizon}.cbm", list(enhanced.get("features", [])))[:20],
            "promotion_candidate": bool(
                delta["directional_accuracy"] >= 0
                and delta["rank_ic"] >= 0
                and delta["sharpe_proxy"] >= 0
                and delta["max_drawdown_proxy"] >= 0
                and rank_ic_wins >= max(1, len(folds) // 2)
            ),
        }
    destination = enhanced_root / "comparison.json"
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
