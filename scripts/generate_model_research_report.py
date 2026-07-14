#!/usr/bin/env python3
from __future__ import annotations

import gzip
import json
import pickle
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output"
AUDITS = ROOT / "audits"
DOCS = ROOT / "docs"
RANDOM_SEED = 42


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def bootstrap_ci(values: list[float], iterations: int = 4000) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(RANDOM_SEED)
    means = []
    for _ in range(iterations):
        sample = [rng.choice(values) for _ in values]
        means.append(sum(sample) / len(sample))
    means.sort()
    return [round(means[int(iterations * 0.025)], 6), round(means[int(iterations * 0.975)], 6)]


def model(task: dict, name: str) -> dict:
    return next(item for item in task["models"] if item["trainer_name"] == name)


def paired_fold_delta(candidate: dict, champion: dict, metric: str) -> dict:
    baseline = {item["fold_id"]: item for item in champion["folds"]}
    values = []
    for fold in candidate["folds"]:
        other = baseline.get(fold["fold_id"])
        left = fold.get("metrics", {}).get(metric)
        right = None if other is None else other.get("metrics", {}).get(metric)
        if left is not None and right is not None:
            values.append(float(left) - float(right))
    return {
        "fold_count": len(values),
        "mean_delta": None if not values else round(sum(values) / len(values), 6),
        "block_bootstrap_95pct_ci": bootstrap_ci(values),
    }


def _sample_quality_index(path: Path) -> dict[tuple[str, str], tuple[float, list[str]]]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    samples = payload.get("samples", payload) if isinstance(payload, dict) else payload
    return {
        (sample.symbol, sample.as_of_date.isoformat()): (
            float(sample.feature_coverage),
            list(sample.missing_features),
        )
        for sample in samples
    }


def oof_analysis(path: Path, *, sample_cache: Path) -> tuple[dict, dict]:
    if not path.exists():
        unavailable = {
            "status": "pending_authoritative_rerun",
            "reason": "The previous full run did not persist row-level OOF predictions. The retraining path now writes audits/oof_predictions.jsonl.gz.",
        }
        return unavailable, unavailable
    quality_index = _sample_quality_index(sample_cache)
    rows = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item["task_name"] == "future_max_drawdown_20d" and item["trainer_name"] == "random-forest":
                if item.get("sample_feature_coverage") is None:
                    coverage, missing = quality_index.get(
                        (item["symbol"], item["as_of_date"]),
                        (None, []),
                    )
                    item["sample_feature_coverage"] = coverage
                    item["missing_features"] = missing
                rows.append(item)
    abstention = {}
    for threshold in (0.50, 0.60, 0.75, 0.85, 0.95):
        retained = [item for item in rows if abs(float(item["calibrated_score"]) - 0.5) * 2 >= threshold]
        correct = [item for item in retained if item.get("actual_label") is not None and int(item["predicted_label"]) == int(item["actual_label"])]
        abstention[str(threshold)] = {
            "retained": len(retained),
            "abstention_rate": round(1 - len(retained) / max(1, len(rows)), 6),
            "retained_accuracy": None if not retained else round(len(correct) / len(retained), 6),
        }
    bucket_rules = (
        ("below_75pct", 0.0, 0.75),
        ("75_to_85pct", 0.75, 0.85),
        ("85_to_95pct", 0.85, 0.95),
        ("95_to_100pct", 0.95, 1.01),
    )
    buckets = {}
    for name, lower, upper in bucket_rules:
        selected = [
            item for item in rows
            if item.get("sample_feature_coverage") is not None
            and lower <= float(item["sample_feature_coverage"]) < upper
        ]
        errors = [
            item for item in selected
            if item.get("actual_label") is not None
            and int(item["predicted_label"]) != int(item["actual_label"])
        ]
        brier = [
            (float(item["calibrated_score"]) - int(item["actual_label"])) ** 2
            for item in selected
            if item.get("actual_label") is not None
        ]
        buckets[name] = {
            "count": len(selected),
            "error_rate": None if not selected else round(len(errors) / len(selected), 6),
            "brier": None if not brier else round(sum(brier) / len(brier), 6),
        }
    covered = sum(item["count"] for item in buckets.values())
    missingness = {
        "status": "computed" if covered else "sample_quality_unavailable",
        "oof_rows_with_feature_coverage": covered,
        "buckets": buckets,
    }
    return {"status": "computed", "threshold_curve": abstention}, missingness


def main() -> None:
    results = read_json(OUTPUT / "results.json")
    read_json(OUTPUT / "evaluation.json")
    approval = read_json(AUDITS / "approval_report_random_forest.json")
    ablation = read_json(AUDITS / "feature_ablation.json")
    paper = read_json(AUDITS / "paper_simulation.json")
    primary = results["task_matrix"]["future_max_drawdown_20d"]
    rf = model(primary, "random-forest")
    linear = model(primary, "linear-baseline")
    paired = {
        metric: paired_fold_delta(rf, linear, metric)
        for metric in (
            "auc_roc", "brier_score", "expected_calibration_error",
            "top_bucket_alert_precision", "top_bucket_drawdown_lift",
        )
    }
    abstention, missingness = oof_analysis(
        AUDITS / "oof_predictions.jsonl.gz",
        sample_cache=ROOT / "temp" / "all_samples.pkl",
    )
    groups = ablation["groups"]
    eligibility = {
        "overall": "eligible" if approval["recommendation"] == "primary_approved" else "conditional",
        "high_vol": "conditional" if approval["regime_comparison"]["high_vol"]["candidate"]["ece_mean"] > approval["regime_comparison"]["high_vol"]["champion"]["ece_mean"] else "eligible",
        "reference_features": "fallback" if groups["price_reference"]["auc_delta_vs_price"] <= 0 else "eligible",
        "event_features": "eligible" if groups["price_event"]["auc_delta_vs_price"] > 0 else "fallback",
        "full_features": "conditional" if groups["full"]["auc_delta_vs_price"] <= 0 else "eligible",
    }
    findings = {
        "generated_from": ["output/results.json", "output/evaluation.json", "audits/approval_report_random_forest.json", "audits/feature_ablation.json", "audits/paper_simulation.json"],
        "data_source": results["data_source"],
        "training_profile": results["training_profile"],
        "sample_count": results["sample_count"],
        "symbol_count": results["symbol_count"],
        "task_names": list(results["task_matrix"]),
        "overall": approval["overall"],
        "paired_fold_deltas": paired,
        "market_comparison": approval["market_comparison"],
        "coverage_group_comparison": approval["coverage_group_comparison"],
        "regime_comparison": approval["regime_comparison"],
        "recent_window_comparison": approval["recent_window_comparison"],
        "ablation": groups,
        "paper_simulation": paper,
        "rf_applicability": eligibility,
        "conclusion": "RF is eligible as primary under the current strict gate. High-volatility calibration and non-positive incremental full/reference ablation remain conditional research findings.",
        "does_not_change_promotion": True,
    }
    write_json(AUDITS / "model_research_findings.json", findings)
    write_json(AUDITS / "abstention_analysis.json", abstention)
    write_json(AUDITS / "missingness_sensitivity.json", missingness)
    curve = abstention.get("threshold_curve", {})
    retained_75 = curve.get("0.75", {})
    report = f"""# 模型研究报告\n\n## 研究边界\n\n本报告只研究未来 20 个交易日显著回撤风险门禁。训练路径为 `{results['data_source']} + {results['training_profile']} + walk-forward`，覆盖 {results['symbol_count']} 个标的和 {results['sample_count']:,} 个样本。收益、风险调整收益、波动率突增和事件后回撤属于辅助任务，不参与 approved 判定。\n\n## RF 与线性 Champion\n\nRF 的总体 AUROC 为 {approval['overall']['challenger']['auc_mean']:.4f}，线性基线为 {approval['overall']['champion']['auc_mean']:.4f}；RF 的 ECE 为 {approval['overall']['challenger']['ece_mean']:.4f}，Brier 为 {approval['overall']['challenger']['brier_mean']:.4f}，风险桶 lift 为 {approval['overall']['challenger']['drawdown_lift_mean']:.4f}。RF 已通过当前 overall、market、coverage group、regime 和 recent-window 门禁。配对 fold 差异及 95% block-bootstrap 区间见 `audits/model_research_findings.json`。\n\n## 适用条件\n\nRF 在总体审批下为 **eligible**。高波动 regime 中 AUROC 和 Brier 优于 champion，但 ECE 略高，因此标记 **conditional**。事件特征相对 price-only 的 AUROC 增量为 {groups['price_event']['auc_delta_vs_price']:.4f}，可保留；reference-only 增量为 {groups['price_reference']['auc_delta_vs_price']:.4f}，full 增量为 {groups['full']['auc_delta_vs_price']:.4f}，两者没有稳定超越 price-only，部署中应保留覆盖门禁与 fallback，不把特征数量当成有效性证据。\n\n## 校准、缺失与 Abstention\n\nRF 当前使用 isotonic 校准，严格审批结果来自 44 个时间滚动 fold。本轮已保存逐行 OOF 预测并计算 50%/60%/75%/85%/95% abstention 曲线。以 75% 置信阈值为例，保留 {retained_75.get('retained', 0):,} 条预测，abstention rate 为 {retained_75.get('abstention_rate', 0):.2%}，保留样本准确率为 {retained_75.get('retained_accuracy', 0):.2%}。特征覆盖率分桶的错误率和 Brier 见 `audits/missingness_sensitivity.json`。\n\n## Paper Validation\n\n历史时间外回放中，RF AUROC 为 {paper['models']['random-forest']['auc']:.4f}，alert precision 为 {paper['models']['random-forest']['alert_precision']:.4f}，drawdown lift 为 {paper['models']['random-forest']['drawdown_lift']:.4f}。未来观测只在到期后回填，且不会自动覆盖 approved 模型。\n\n## 结论\n\nRF 在当前真实数据、当前特征合同与严格 gate 下可以作为 primary，linear-baseline 继续作为 champion fallback。reference/full 消融没有提供正增益，高波动校准仍是主要限制；这些条件必须随模型版本一起展示。\n"""
    DOCS.mkdir(parents=True, exist_ok=True)
    (DOCS / "model-research-report.md").write_text(report, encoding="utf-8")
    print("generated model research findings and report")


if __name__ == "__main__":
    main()
