"""§1 row-2: train the CatBoost short-term direction model on the archived
OOF predictions (REAL data).

Reads ``artifacts/long_term_training/latest.predictions.parquet``, builds
feature rows (the existing model's score, feature_coverage, regime,
industry_key, data_quality_status) + a binary direction label
(``target > 0 → 1 else 0``), trains via ``CatBoostShortTermRunner``, + saves
the ``.cbm`` artifact to ``artifacts/short_term/catboost_direction.cbm``.

The model is a stacking/enhancement direction model on REAL OOF data (the
existing model's predictions + regime/industry context → actual direction).
Run with::

    NODE_ENV=development python3 -m scripts.train_catboost_short_term
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
    up = sum(1 for r in rows if r["label"] == 1)
    print(f"built {len(rows)} OOF rows from {parquet.name} (up: {up}, down: {len(rows)-up})")
    runner = CatBoostShortTermRunner(root)
    result = runner.train(rows, iterations=200, verbose=False)
    print("train:", result)
    # Sanity: predict on the first row (real OOF feature row).
    if rows:
        pred = runner.predict(rows[0])
        print("sample predict:", pred)
    return result


if __name__ == "__main__":
    main()
