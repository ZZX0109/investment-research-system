from __future__ import annotations

from pathlib import Path

from ml.data.build_dataset import build_dataset
from ml.inference.predict import infer
from ml.training.train import train_model


def run() -> None:
    dataset = Path("artifacts/datasets/test_contract")
    result = build_dataset(["NVDA", "TSLA"], dataset, allow_synthetic=True, smoke=True)
    assert result["sampleCount"] > 0
    trained = train_model("tabular_baseline", dataset, epochs=1, model_id="test_contract_model")
    assert trained["ok"] is True
    prediction = infer("NVDA", "us", model_id="test_contract_model", allow_synthetic=True, write_sqlite=True)
    assert prediction["ok"] is True
    assert prediction["modelId"] == "test_contract_model"
    assert prediction["asOfDate"]
    assert prediction["validUntil"]
    assert prediction["calibrationStatus"] in {"valid", "stale", "failed"}
    if prediction["calibrationStatus"] == "failed":
        assert "calibration_ece" in prediction["validationMetrics"]


if __name__ == "__main__":
    run()
    print("test_inference_contract ok")
