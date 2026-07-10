from __future__ import annotations

import argparse
import json

from ml.training.registry import latest_approved_model, list_models


def calibration_status(model: dict | None) -> dict:
    if not model:
        return {"ok": False, "calibrationStatus": "missing", "reason": "No approved or requested model."}
    metrics = model.get("metrics", {})
    ece = float(metrics.get("calibration_ece", 1.0))
    pinball = float(metrics.get("pinball_loss", 1.0))
    crps = float(metrics.get("crps", 1.0))
    breach_rate = float(metrics.get("var_breach_rate", 1.0))
    status = "valid" if ece <= 0.12 and pinball <= 0.2 and 0.01 <= breach_rate <= 0.35 else "failed"
    return {
        "ok": status == "valid",
        "calibrationStatus": status,
        "modelId": model["model_id"],
        "ece": ece,
        "pinballLoss": pinball,
        "crps": crps,
        "varBreachRate": breach_rate,
        "walkForward": metrics.get("walk_forward"),
        "purgedCv": metrics.get("purged_cv"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", default=None)
    args = parser.parse_args()
    model = None
    if args.model_id:
        model = next((item for item in list_models() if item["model_id"] == args.model_id), None)
    else:
        model = latest_approved_model()
    print(json.dumps(calibration_status(model), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
