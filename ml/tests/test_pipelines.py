from __future__ import annotations

from ml.pipelines.minimal_demo import run_minimal_demo
from ml.pipelines.reliable_scale import run_reliable_scale


def run() -> None:
    minimal = run_minimal_demo(
        symbols=["NVDA", "TSLA", "QQQ", "XLE"],
        model_id="test_pipeline_minimal",
        allow_synthetic=True,
        smoke=True,
    )
    assert minimal["ok"] is True
    assert minimal["modelCard"]["passed"] is True
    assert minimal["modelCard"]["dataset"]["pointInTimeFutureLeakageCount"] == 0
    assert minimal["modelCard"]["inferencePreview"]

    scaled = run_reliable_scale(
        model_id="test_pipeline_scale",
        allow_synthetic=True,
        smoke=True,
        max_symbols=8,
        min_symbols=6,
        min_samples=192,
        run_id="test_reliable_scale_smoke",
        dataset_id="test_reliable_scale_smoke",
    )
    assert scaled["ok"] is True
    assert scaled["scaleReadinessReport"]["readiness"] == "pass"
    assert scaled["datasetStats"]["symbolCount"] >= 6
    assert scaled["datasetStats"]["sampleCount"] >= 192
    assert scaled["modelCard"]["metrics"]["walk_forward"]["windowCount"] >= 2
    assert scaled["modelCard"]["metrics"]["purged_cv"]["foldCount"] >= 3


if __name__ == "__main__":
    run()
    print("test_pipelines ok")
