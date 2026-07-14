#!/usr/bin/env python3
"""Build a shareable, provenance-checked experiment report from authoritative artifacts."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT, AUDITS, DOCS = ROOT / "output", ROOT / "audits", ROOT / "docs"


def read(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"Required authoritative artifact missing: {path.name}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    results = read(OUTPUT / "results.json")
    evaluation = read(OUTPUT / "evaluation.json")
    coverage = read(AUDITS / "data_coverage.json")
    labels = read(AUDITS / "label_coverage.json")
    pit = read(AUDITS / "pit_audit.json")
    regimes = read(AUDITS / "regime_breakdown.json")
    identity = {
        "training_run_id": results.get("run_label"),
        "sample_snapshot_hash": results.get("sample_snapshot_hash"),
        "feature_contract_version": results.get("feature_contract_version"),
        "data_version": results.get("data_source"),
    }
    if not identity["training_run_id"] or not identity["sample_snapshot_hash"] or not identity["feature_contract_version"]:
        raise RuntimeError("Results lacks a reproducible training run identity")
    for name, artifact in {
        "evaluation": evaluation,
        "data_coverage": coverage,
        "label_coverage": labels,
        "pit_audit": pit,
        "regime_breakdown": regimes,
    }.items():
        artifact_identity = {
            "training_run_id": artifact.get("training_run_id"),
            "sample_snapshot_hash": artifact.get("sample_snapshot_hash"),
            "feature_contract_version": artifact.get("feature_contract_version"),
            "data_version": artifact.get("data_version") or artifact.get("data_source"),
        }
        if artifact_identity != identity:
            raise RuntimeError(f"{name} identity does not match authoritative results")
    if not coverage.get("markets") or not any(item.get("provider_usage") for item in coverage["markets"].values()):
        raise RuntimeError("Provider coverage is missing from the public experiment inputs")
    primary = results.get("deployment_roles", {}).get("primary_model", "random-forest")
    manifest = {
        "schema_version": "public-experiment-manifest-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "identity": identity,
        "split_strategy": "walk-forward / purged-CV when configured by the training run; no random split is used for approval",
        "random_seed": 42,
        "universe": results.get("universe_distribution", {}),
        "included_markets": results.get("included_markets", []),
        "excluded_markets": results.get("excluded_markets", []),
        "data_coverage": coverage,
        "label_coverage": labels,
        "pit_audit": pit,
        "regime_breakdown": regimes,
        "model_comparison": evaluation.get("models", {}),
        "task_matrix": evaluation.get("task_matrix", {}),
        "deployment_roles": results.get("deployment_roles", {}),
        "survivorship_bias": {
            "status": "unresolved",
            "statement": "The universe is a versioned current coverage preset. Delisted, unavailable, halted, and provider-missing instruments are reported as exclusions; this run does not claim to eliminate historical constituent or survivorship bias.",
        },
        "public_data_policy": "Only aggregates, hashes and provider coverage are published; raw news, credentials and account data are excluded.",
    }
    OUTPUT.joinpath("public_experiment_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    model_metrics = evaluation.get("models", {}).get(primary, {})
    DOCS.mkdir(exist_ok=True)
    DOCS.joinpath("public-experiment-report.md").write_text(
        "# 公开实验报告\n\n"
        f"- 训练运行：`{identity['training_run_id']}`\n"
        f"- 样本快照：`{identity['sample_snapshot_hash']}`\n"
        f"- 特征合同：`{identity['feature_contract_version']}`\n"
        f"- 数据模式：`{identity['data_version']}`；随机种子：`42`\n"
        f"- 纳入市场：{', '.join(manifest['included_markets']) or 'none'}\n\n"
        "## 验证与限制\n\n"
        "审批只使用时间序列 walk-forward/Purged CV 配置，不使用随机切分。PIT 审计、provider 覆盖、缺失率、股票池与市场排除原因均见同目录 manifest。股票池是版本化 coverage preset，不声称消除幸存者偏差；退市、停牌和 provider 缺失均是当前限制。\n\n"
        "## 主模型\n\n"
        f"`{primary}`：AUROC `{model_metrics.get('auc_mean')}`，ECE `{model_metrics.get('ece_mean')}`，Brier `{model_metrics.get('brier_mean')}`，风险桶 precision `{model_metrics.get('alert_precision_mean')}`。未获批模型保持 research-only；失败与门禁原因来自 evaluation/task matrix。\n",
        encoding="utf-8",
    )
    print("Wrote output/public_experiment_manifest.json and docs/public-experiment-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
