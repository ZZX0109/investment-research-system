"""§1 row-2: evaluate the CatBoost short-term direction model's HONEST OOF
directional accuracy (train/test split, never in-sample).

Reads the archived OOF parquet, splits into train (80%) / holdout (20%),
trains a CatBoost on the train split, evaluates directional accuracy +
per-class precision/recall on the holdout, + saves the summary to
``artifacts/short_term/catboost_direction_accuracy.json`` so the
``get_four_task_forecasts`` tool can cite "CatBoost OOF 方向命中 X%"
(训练说清楚 — the model's real accuracy, not a hidden number).

Run with::

    NODE_ENV=development python3 -m scripts.evaluate_catboost_short_term
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


def main(project_root: str = ".") -> dict:
    import pyarrow.parquet as pq

    from investment_research.training.short_term import CatBoostShortTermRunner

    root = Path(project_root).resolve()
    parquet = root / "artifacts" / "long_term_training" / "latest.predictions.parquet"
    if not parquet.exists():
        raise FileNotFoundError(f"OOF parquet missing: {parquet}")
    table = pq.read_table(
        parquet,
        columns=[
            "split", "symbol", "decision_date", "industry_key", "regime",
            "feature_coverage", "data_quality_status", "target", "score",
        ],
    )
    rows: list[dict] = []
    for r in table.to_pylist():
        if str(r.get("split", "")) != "oof":
            continue
        target = r.get("target")
        score = r.get("score")
        if target is None or score is None:
            continue
        rows.append(
            {
                "score": float(score),
                "feature_coverage": float(r.get("feature_coverage", 1.0) or 1.0),
                "regime": str(r.get("regime") or "unknown"),
                "industry_key": str(r.get("industry_key") or "unknown"),
                "data_quality_status": str(r.get("data_quality_status") or "unknown"),
                "label": 1 if float(target) > 0 else 0,
            }
        )
    print(f"built {len(rows)} OOF rows from {parquet.name}")
    runner = CatBoostShortTermRunner(root)
    summary = runner.evaluate_with_split(rows, test_frac=0.2, iterations=200)
    print("evaluate:", summary)
    return summary


if __name__ == "__main__":
    main()
