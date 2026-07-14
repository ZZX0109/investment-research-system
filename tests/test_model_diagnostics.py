from pathlib import Path

from investment_research.pipeline.model_diagnostics import ModelDiagnosticsService
from investment_research.pipeline.model_inference import SnapshotFeatureVector


def test_runtime_diagnostics_marks_out_of_training_range(tmp_path: Path) -> None:
    (tmp_path / "scaler_params.json").write_text(
        '{"feature_order":["ret_20d"],"mean":[0.0],"scale":[0.01]}', encoding="utf-8"
    )
    result = ModelDiagnosticsService(tmp_path).evaluate(
        SnapshotFeatureVector(feature_order=["ret_20d"], values=[0.2], feature_coverage=1.0)
    )
    assert result.out_of_range_features == ["ret_20d"]
    assert "training range" in result.warnings[0]
