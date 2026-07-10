from __future__ import annotations

from ml.pipelines.common import deep_candidate_audit
from ml.training.registry import approval_status


def run() -> None:
    weak = deep_candidate_audit(
        [
            {
                "ok": True,
                "modelId": "weak_cnn",
                "modelType": "cnn_tcn",
                "artifactPath": "artifacts/models/weak_cnn/model.pt",
                "metrics": {
                    "model_impl": "torch_lightweight_candidate",
                    "evaluated_sample_count": 120,
                    "walk_forward": {"windowCount": 3},
                    "purged_cv": {"foldCount": 3},
                    "risk_regime_accuracy": 0.5,
                    "risk_regime_f1_macro": 0.5,
                    "calibration_ece": 0.05,
                    "pinball_loss": 0.05,
                    "crps": 0.2,
                    "var_breach_rate": 0.8,
                },
            }
        ]
    )
    assert weak["status"] == "fail"
    assert weak["candidates"][0]["candidateStatus"] == "failed_candidate"

    strong = deep_candidate_audit(
        [
            {
                "ok": True,
                "modelId": "strong_transformer",
                "modelType": "itransformer_lite",
                "artifactPath": "artifacts/models/strong_transformer/model.pt",
                "metrics": {
                    "model_impl": "torch_lightweight_candidate",
                    "evaluated_sample_count": 120,
                    "walk_forward": {"windowCount": 3},
                    "purged_cv": {"foldCount": 3},
                    "risk_regime_accuracy": 0.5,
                    "risk_regime_f1_macro": 0.5,
                    "calibration_ece": 0.05,
                    "pinball_loss": 0.05,
                    "crps": 0.2,
                    "var_breach_rate": 0.12,
                },
            }
        ]
    )
    assert strong["status"] == "pass"
    assert strong["candidates"][0]["candidateStatus"] == "promotable_candidate"
    assert approval_status(strong["candidates"][0]["metrics"], "itransformer_lite") == "candidate"
    assert approval_status(strong["candidates"][0]["metrics"], "tabular_baseline") == "approved"
    assert approval_status({**strong["candidates"][0]["metrics"], "source_status": {"degraded": 1}}, "tabular_baseline") == "candidate"


if __name__ == "__main__":
    run()
    print("test_deep_candidate_audit ok")
