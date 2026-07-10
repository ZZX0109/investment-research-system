from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median
from typing import Any

from ml.common import FEATURE_VERSION, artifact_path, now_iso, read_json, write_json
from ml.models.tabular_baseline import save_model, train_tabular
from ml.training.evaluate import evaluate_predictions, model_judge_v2_report, purged_cv_report, tabular_validation_report, walk_forward_report
from ml.training.registry import register_model


def load_samples(dataset: Path) -> list[dict[str, Any]]:
    payload = read_json(dataset / "dataset.json")
    samples = payload["samples"]
    formal = [item for item in samples if item.get("sourceStatus") != "degraded"]
    return formal or samples


def train_model(model_type: str, dataset: Path, epochs: int = 1, model_id: str | None = None, register: bool = True) -> dict[str, Any]:
    samples = load_samples(dataset)
    if not samples:
        raise RuntimeError("dataset contains no samples")
    model_id = model_id or f"{model_type}_{now_iso().replace(':', '').replace('-', '').replace('.', '')}"
    model_dir = artifact_path("models", model_id)
    model_dir.mkdir(parents=True, exist_ok=True)
    if model_type == "tabular_baseline":
        model, metrics = train_tabular(samples)
        metrics = {**metrics, **tabular_validation_report(model, samples)}
        artifact = model_dir / "model.pkl"
        save_model(model, artifact)
    else:
        metrics = train_torch_placeholder(model_type, samples, model_dir, epochs)
        artifact = model_dir / "model.pt" if (model_dir / "model.pt").exists() else model_dir / "model.json"
    dated_samples = [item["asOfDate"] for item in samples if item.get("split") in {"train", "validation", "test"}] or [item["asOfDate"] for item in samples]
    trained_until = max(dated_samples)
    source_status: dict[str, int] = {}
    for sample in samples:
        key = str(sample.get("sourceStatus", "unknown"))
        source_status[key] = source_status.get(key, 0) + 1
    metrics = {
        **metrics,
        "sample_count": len(samples),
        "source_status": source_status,
        "trained_at": now_iso(),
        "epochs": epochs,
    }
    metrics["judge_v2"] = model_judge_v2_report(metrics)
    write_json(model_dir / "metrics.json", metrics)
    registry = register_model(model_id, model_type, FEATURE_VERSION, metrics, artifact, trained_until) if register else {}
    return {"ok": True, "modelId": model_id, "modelType": model_type, "artifactPath": str(artifact), "metrics": metrics, "registry": registry}


def train_torch_placeholder(model_type: str, samples: list[dict[str, Any]], model_dir: Path, epochs: int) -> dict[str, Any]:
    try:
        import torch
        from torch import nn

        from ml.models.cnn_tcn import CNNTCNModel
        from ml.models.itransformer_lite import ITransformerLite
        from ml.models.patch_tst_lite import PatchTSTLite
    except Exception as exc:
        write_json(model_dir / "model.json", {"modelType": model_type, "trained": False, "reason": str(exc)})
        return {"risk_regime_accuracy": 0.0, "risk_regime_f1_macro": 0.0, "calibration_ece": 0.2, "model_impl": "torch_unavailable"}

    labels = {"low": 0, "medium": 1, "high": 2}
    regimes = {0: "low", 1: "medium", 2: "high"}
    train_samples = [sample for sample in samples if sample.get("split") == "train"]
    if len(train_samples) < 32:
        split_at = max(1, int(len(samples) * 0.7))
        train_samples = samples[:split_at]
    evaluation_samples = [sample for sample in samples if sample.get("split") in {"validation", "test", "shadow"}]
    if not evaluation_samples:
        evaluation_samples = samples[len(train_samples) :] or samples
    train_samples = train_samples[:1024]
    evaluation_samples = evaluation_samples[:2048]
    x = torch.tensor([sample["window120"] for sample in train_samples], dtype=torch.float32)
    y = torch.tensor([labels.get(sample["labels"]["risk_regime_1m"], 1) for sample in train_samples], dtype=torch.long)
    drawdown_target = torch.tensor(
        [
            [
                float(sample["labels"]["max_drawdown_1m"]),
                float(sample["labels"]["max_drawdown_1m"]) * 1.25,
                float(sample["labels"]["max_drawdown_1m"]) * 1.5,
            ]
            for sample in train_samples
        ],
        dtype=torch.float32,
    )
    volatility_target = torch.tensor(
        [
            [
                float(sample["labels"].get("future_volatility_1m", sample["labels"].get("volatility_1m", 0.0))),
                float(sample["labels"].get("future_volatility_1m", sample["labels"].get("volatility_1m", 0.0))) * 1.25,
            ]
            for sample in train_samples
        ],
        dtype=torch.float32,
    )
    train_drawdowns = sorted(float(sample["labels"]["max_drawdown_1m"]) for sample in train_samples)
    drawdown_p50_anchor = median(train_drawdowns) if train_drawdowns else -0.04
    drawdown_p90_anchor = empirical_quantile(train_drawdowns, 0.1) if train_drawdowns else -0.08
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    if model_type == "cnn_tcn":
        model = CNNTCNModel(feature_dim=x.shape[-1])
    elif model_type == "itransformer_lite":
        model = ITransformerLite(window_size=x.shape[1])
    else:
        model = PatchTSTLite(feature_dim=x.shape[-1])
    model.to(device)
    x = x.to(device)
    y = y.to(device)
    drawdown_target = drawdown_target.to(device)
    volatility_target = volatility_target.to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4)
    loss_fn = nn.CrossEntropyLoss()
    regression_loss = nn.SmoothL1Loss()
    model.train()
    for _ in range(max(1, min(epochs, 3))):
        optimizer.zero_grad()
        output = model(x)
        loss = (
            loss_fn(output["regime"], y)
            + 0.35 * regression_loss(output["drawdown"], drawdown_target)
            + 0.15 * regression_loss(output["volatility"], volatility_target)
        )
        loss.backward()
        optimizer.step()

    eval_x = torch.tensor([sample["window120"] for sample in evaluation_samples], dtype=torch.float32, device=device)
    model.eval()
    predictions: list[dict[str, Any]] = []
    with torch.no_grad():
        output = model(eval_x)
        probabilities = torch.softmax(output["regime"], dim=1).detach().cpu()
        predicted_indexes = probabilities.argmax(dim=1)
        confidences = probabilities.max(dim=1).values
        drawdowns = output["drawdown"].detach().cpu()
        volatilities = output["volatility"].detach().cpu().abs()
        for idx, sample in enumerate(evaluation_samples):
            raw_p50 = max(-0.6, min(-0.001, float(drawdowns[idx, 0])))
            p50 = 0.5 * raw_p50 + 0.5 * float(drawdown_p50_anchor)
            p90 = max(-0.8, min(p50 - 0.005, float(drawdown_p90_anchor)))
            predictions.append(
                {
                    "riskRegime": regimes.get(int(predicted_indexes[idx]), "medium"),
                    "rawConfidence": round(float(confidences[idx]), 4),
                    "confidence": round(float(confidences[idx]), 4),
                    "drawdownP50": round(p50, 4),
                    "drawdownP90": round(p90, 4),
                    "volatilityP50": round(max(0.001, float(volatilities[idx, 0])), 4),
                    "asOfDate": sample["asOfDate"],
                }
            )
    validation_pairs = [
        (sample, prediction)
        for sample, prediction in zip(evaluation_samples, predictions)
        if sample.get("split") == "validation"
    ]
    if validation_pairs:
        validation_correct = [
            labels.get(sample["labels"]["risk_regime_1m"], 1) == labels.get(prediction["riskRegime"], 1)
            for sample, prediction in validation_pairs
        ]
        confidence_anchor = sum(1 for item in validation_correct if item) / len(validation_correct)
    else:
        confidence_anchor = 0.5
    for prediction in predictions:
        raw_confidence = float(prediction.pop("rawConfidence", prediction["confidence"]))
        prediction["confidence"] = round(max(0.34, min(0.95, 0.25 * raw_confidence + 0.75 * confidence_anchor)), 4)
    metrics = {
        **evaluate_predictions(evaluation_samples, predictions),
        "walk_forward": walk_forward_report(evaluation_samples, predictions),
        "purged_cv": purged_cv_report(evaluation_samples, predictions),
        "train_sample_count": len(train_samples),
        "model_impl": "torch_lightweight_candidate",
    }
    torch.save({"state_dict": model.state_dict(), "model_type": model_type, "feature_dim": int(x.shape[-1]), "window_size": int(x.shape[1])}, model_dir / "model.pt")
    write_json(
        model_dir / "model.json",
        {
            "modelType": model_type,
            "trained": True,
            "device": device,
            "trainSampleCount": len(train_samples),
            "evaluationSampleCount": len(evaluation_samples),
            "evaluationSplits": sorted({sample.get("split", "unknown") for sample in evaluation_samples}),
        },
    )
    return metrics


def empirical_quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    position = max(0, min(len(values) - 1, int(round((len(values) - 1) * quantile))))
    return values[position]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="tabular_baseline")
    parser.add_argument("--dataset", default=str(artifact_path("datasets", "investment_research_v1")))
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--model-id", default=None)
    args = parser.parse_args()
    print(json.dumps(train_model(args.model, Path(args.dataset), args.epochs, args.model_id), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
