from __future__ import annotations

import json

import pyarrow.parquet as pq

from investment_research.training.evaluation_artifacts import write_compact_evaluation


def test_evaluation_summary_externalizes_prediction_rows(tmp_path) -> None:
    result = {
        "scope_id": "cn:close_confirmed:drawdown_20d",
        "fold_hash": "a" * 64,
        "selected_candidate": "logistic-regression",
        "candidates": [{
            "name": "logistic-regression",
            "brier": 0.2,
            "raw_oof_scores": [0.1, 0.9],
            "oof_scores": [0.2, 0.8],
            "oof_labels": [0, 1],
            "oof_fold_ids": ["fold-1", "fold-1"],
        }],
        "holdout_scores": [0.4],
        "holdout_labels": [0],
        "stress_scores": [0.7],
        "stress_labels": [1],
    }
    path = tmp_path / "predictions.parquet"
    summary, digest = write_compact_evaluation(
        "drawdown_20d", result, path, reference="artifacts/predictions.parquet"
    )

    assert summary["prediction_artifact"]["ref"] == "artifacts/predictions.parquet"
    assert summary["prediction_artifact"]["sha256"] == digest
    assert "oof_scores" not in json.dumps(summary)
    table = pq.read_table(path)
    assert table.num_rows == 4
    assert set(table.column_names) >= {"split", "candidate", "prediction_json", "target_json"}
