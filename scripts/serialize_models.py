"""Serialize approved training models to disk for deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

import joblib
from investment_research.feature_contract import (
    FEATURE_CONTRACT_VERSION,
    INVESTMENT_RISK_FEATURE_ORDER,
)

warnings.filterwarnings(
    "ignore",
    message=".*encountered in matmul",
    category=RuntimeWarning,
    module=r"sklearn\..*",
)


class PackageRenameUnpickler(pickle.Unpickler):
    """Read artifacts pickled before the package rename."""

    def find_class(self, module: str, name: str):
        if module.startswith("investment_workbuddy"):
            module = module.replace("investment_workbuddy", "investment_research", 1)
        return super().find_class(module, name)


def load_pickle(path: Path):
    with open(path, "rb") as f:
        return PackageRenameUnpickler(f).load()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serialize approved training models.")
    parser.add_argument(
        "--report", type=Path, default=PROJECT / "temp" / "experiment_report.pkl"
    )
    parser.add_argument(
        "--results", type=Path, default=PROJECT / "output" / "results.json"
    )
    parser.add_argument(
        "--invest-config",
        type=Path,
        default=PROJECT / "output" / "invest_agent_models.json",
    )
    parser.add_argument(
        "--samples", type=Path, default=PROJECT / "temp" / "all_samples.pkl"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT / "output" / "models"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    models_dir = args.output_dir
    models_dir.mkdir(parents=True, exist_ok=True)

    results = load_json(args.results)
    approved_config = load_json(args.invest_config)
    approved_models = list(approved_config.get("approved_models", []))
    approved_trainers = [
        model.get("trainer_name")
        for model in approved_models
        if model.get("trainer_name")
    ]
    primary_model = approved_config.get("primary_model") or {}
    champion_fallback = (
        approved_config.get("champion_fallback")
        or approved_config.get("champion_model")
        or {}
    )

    print("Loading training data...")
    data = load_pickle(args.samples)
    samples = data.get("samples", [])
    if not samples:
        print("No samples — cannot serialize models")
        return 0

    feature_order, x_matrix, labels = build_matrix(
        samples, results.get("target_name", "future_max_drawdown_20d")
    )

    import numpy as np
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler

    x_np = np.array(x_matrix)
    y_np = np.array(labels)
    imputer = SimpleImputer(strategy="median")
    x_np = imputer.fit_transform(x_np)
    joblib.dump(imputer, models_dir / "imputer.pkl")
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x_np)

    print(
        f"Training data: {x_scaled.shape}, labels: {len(y_np)} samples, {y_np.sum():.0f} positive"
    )

    feature_metadata = {
        "feature_order": feature_order,
        "n_features": len(feature_order),
        "n_samples": len(y_np),
        "positive_labels": int(y_np.sum()),
        "data_source": results.get("data_source"),
        "training_profile": results.get("training_profile"),
        "training_generated_at": results.get("generated_at"),
        "target_name": results.get("target_name", "future_max_drawdown_20d"),
        "imputer_strategy": "median",
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
        "minimum_inference_feature_coverage": 0.75,
        "description": "Approved deployment feature metadata for real + full training.",
    }
    (models_dir / "feature_order.json").write_text(
        json.dumps(feature_metadata, indent=2), encoding="utf-8"
    )
    (models_dir / "scaler_params.json").write_text(
        json.dumps(
            {
                "mean": scaler.mean_.tolist(),
                "scale": scaler.scale_.tolist(),
                "feature_order": feature_order,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    serialized: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for trainer_name in approved_trainers:
        try:
            base_estimator = build_estimator(trainer_name)
            if base_estimator is None:
                skipped[trainer_name] = (
                    "approved model serializer is not implemented for this trainer"
                )
                continue
            model, calibration_method = fit_calibrated_estimator(
                base_estimator, x_scaled, y_np
            )
            file_name = f"{trainer_name}_model.pkl"
            joblib.dump(model, models_dir / file_name)
            serialized[trainer_name] = {
                "path": file_name,
                "status": "approved",
                "trainer_name": trainer_name,
                "target_name": results.get("target_name", "future_max_drawdown_20d"),
                "calibration_method": calibration_method,
            }
            print(f"  {trainer_name:25s} -> {file_name} ({calibration_method})")
        except Exception as exc:
            print(f"  {trainer_name:25s} FAIL: {exc}")
            skipped[trainer_name] = str(exc)

    archive_stale_model_files(
        models_dir, {item["path"] for item in serialized.values()}
    )

    artifact_names = {
        "feature_order.json",
        "scaler_params.json",
        "imputer.pkl",
        *[item["path"] for item in serialized.values()],
    }
    artifact_hashes = {
        name: _sha256(models_dir / name) for name in sorted(artifact_names)
    }
    decision_contexts = sorted(
        {getattr(sample, "decision_context", "close_confirmed") for sample in samples}
    )
    sample_data_hash = _sha256(args.samples)
    dependency_lock = PROJECT / "pyproject.toml"
    summary = {
        "schema_version": "model-artifact-set-v3",
        "data_source": results.get("data_source"),
        "training_profile": results.get("training_profile"),
        "training_generated_at": results.get("generated_at"),
        "target_name": results.get("target_name", "future_max_drawdown_20d"),
        "training_run_id": os.environ.get("INVESTMENT_RESEARCH_TRAINING_RUN_ID") or results.get("run_label"),
        "config_hash": os.environ.get("INVESTMENT_RESEARCH_TRAINING_CONFIG_HASH"),
        "code_commit": os.environ.get("INVESTMENT_RESEARCH_CODE_COMMIT", "unversioned-worktree"),
        "raw_data_hash": os.environ.get("INVESTMENT_RESEARCH_RAW_DATA_HASH"),
        "sample_data_hash": sample_data_hash,
        "data_snapshot_hash": sample_data_hash,
        "feature_contract_version": feature_metadata["feature_contract_version"],
        "label_policy_version": os.environ.get("INVESTMENT_RESEARCH_LABEL_POLICY_VERSION", "multitask-v2"),
        "dependency_lock_hash": _sha256(dependency_lock),
        "random_seeds": [
            int(item)
            for item in os.environ.get("INVESTMENT_RESEARCH_RANDOM_SEEDS", "42").split(",")
            if item.strip()
        ],
        "decision_context": decision_contexts[0] if len(decision_contexts) == 1 else "mixed_forbidden",
        "artifact_hashes": artifact_hashes,
        "legacy_cutoff_semantics": False,
        "primary_model": _deployment_role_entry(
            primary_model, serialized, role="primary"
        ),
        "champion_fallback": _deployment_role_entry(
            champion_fallback, serialized, role="champion_fallback"
        ),
        "approved_challengers": [
            _deployment_role_entry(model, serialized, role="approved_challenger")
            for model in approved_config.get("approved_challengers", [])
            if model.get("trainer_name") in serialized
        ],
        "conditional_models": approved_config.get("conditional_models", []),
        "research_only_models": approved_config.get("research_only_models", []),
        "approved_trainers": sorted(serialized),
        "models": serialized,
        "skipped": skipped,
        "deployment_ready": bool(serialized)
        and len(serialized) == len(approved_trainers),
        "note": "Only approved models are serialized for deployment. Research-only models remain in evaluation outputs only.",
    }
    (models_dir / "model_manifest.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"\nSerialized {len(serialized)} approved models to {models_dir}")
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _deployment_role_entry(
    config_model: dict, serialized: dict[str, dict], *, role: str
) -> dict | None:
    trainer_name = config_model.get("trainer_name")
    if not trainer_name or trainer_name not in serialized:
        return None
    entry = dict(serialized[trainer_name])
    entry["model_id"] = config_model.get("model_id")
    entry["deployment_role"] = role
    return entry


def archive_stale_model_files(models_dir: Path, active_file_names: set[str]) -> None:
    stale_paths = [
        path
        for path in models_dir.glob("*_model.pkl")
        if path.name not in active_file_names
    ]
    if not stale_paths:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_dir = models_dir / "archive" / f"stale_models_{stamp}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for path in stale_paths:
        path.replace(archive_dir / path.name)


def build_matrix(
    samples: list, target_name: str
) -> tuple[list[str], list[list[float]], list[int]]:
    feature_order = list(INVESTMENT_RISK_FEATURE_ORDER)
    x_matrix: list[list[float]] = []
    labels: list[int] = []
    for sample in samples:
        feature_map = (
            sample.features
            if isinstance(sample.features, dict)
            else sample.features.model_dump()
        )
        x_matrix.append(
            [float(feature_map.get(name, 0.0) or 0.0) for name in feature_order]
        )
        label_value = getattr(sample.labels, target_name, None)
        labels.append(1 if (label_value is not None and label_value <= -0.08) else 0)
    return feature_order, x_matrix, labels


def build_estimator(trainer_name: str):
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression

    if trainer_name == "linear-baseline":
        return LogisticRegression(
            max_iter=2000, class_weight="balanced", random_state=42
        )
    if trainer_name == "logistic-regression":
        return LogisticRegression(
            max_iter=2000, class_weight="balanced", random_state=42
        )
    if trainer_name == "random-forest":
        return RandomForestClassifier(
            n_estimators=200,
            max_depth=6,
            min_samples_leaf=2,
            class_weight="balanced_subsample",
            random_state=42,
        )
    if trainer_name == "xgboost":
        import xgboost as xgb

        return xgb.XGBClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            min_child_weight=3,
            random_state=42,
            verbosity=0,
        )
    if trainer_name == "lightgbm":
        import lightgbm as lgb

        return lgb.LGBMClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=5,
            class_weight="balanced",
            random_state=42,
            verbose=-1,
        )
    return None


def fit_calibrated_estimator(estimator, x_scaled, y_np):
    from sklearn.base import clone
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.metrics import brier_score_loss
    from sklearn.model_selection import train_test_split

    if len(set(y_np.tolist())) < 2 or len(y_np) < 20:
        model = CalibratedClassifierCV(estimator, method="sigmoid", cv=2)
        model.fit(x_scaled, y_np)
        return model, "sigmoid"

    x_train, x_valid, y_train, y_valid = train_test_split(
        x_scaled,
        y_np,
        test_size=0.2,
        random_state=42,
        stratify=y_np,
    )
    best_method = "sigmoid"
    best_score = None
    for method in ("sigmoid", "isotonic"):
        candidate = CalibratedClassifierCV(clone(estimator), method=method, cv=3)
        candidate.fit(x_train, y_train)
        probs = candidate.predict_proba(x_valid)[:, 1]
        score = brier_score_loss(y_valid, probs)
        if best_score is None or score < best_score:
            best_score = score
            best_method = method

    final_model = CalibratedClassifierCV(estimator, method=best_method, cv=3)
    final_model.fit(x_scaled, y_np)
    return final_model, best_method


if __name__ == "__main__":
    raise SystemExit(main())
