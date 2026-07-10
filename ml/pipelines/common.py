from __future__ import annotations

from pathlib import Path
from typing import Any

from ml.common import artifact_path, now_iso, read_json, write_json

MINIMAL_SYMBOLS = ["NVDA", "TSLA", "QQQ", "XLE", "510300", "600519"]

REAL_V1_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "AMD", "NFLX",
    "JPM", "V", "MA", "UNH", "LLY", "JNJ", "MRK", "COST", "WMT", "HD",
    "XOM", "CVX", "COP", "SLB", "NEE", "CAT", "GE", "BA", "DE", "HON",
]

SCALED_SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "AMD", "NFLX",
    "JPM", "V", "MA", "UNH", "LLY", "JNJ", "MRK", "COST", "WMT", "HD",
    "XOM", "CVX", "COP", "SLB", "NEE", "CAT", "GE", "BA", "DE", "HON",
    "QQQ", "SPY", "DIA", "IWM", "XLK", "XLE", "XLF", "XLV", "XLY", "TLT",
    "600519", "000858", "300750", "601318", "600036", "601899", "600276", "000333", "510300", "159919",
]

US_SCALE_UNIVERSE_300 = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "AVGO", "TSLA", "AMD",
    "NFLX", "ADBE", "CRM", "ORCL", "CSCO", "INTC", "QCOM", "TXN", "AMAT", "MU",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "AXP", "BLK", "SCHW", "SPGI",
    "V", "MA", "PYPL", "COF", "DFS", "UNH", "LLY", "JNJ", "MRK", "ABBV",
    "PFE", "TMO", "ABT", "DHR", "BMY", "AMGN", "GILD", "CVS", "CI", "HUM",
    "COST", "WMT", "HD", "LOW", "TGT", "MCD", "SBUX", "NKE", "BKNG", "TJX",
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY", "KMI", "HAL",
    "NEE", "SO", "DUK", "D", "AEP", "EXC", "SRE", "PEG", "ED", "XEL",
    "CAT", "GE", "BA", "DE", "HON", "RTX", "LMT", "NOC", "UPS", "FDX",
    "UNP", "CSX", "NSC", "MMM", "EMR", "ETN", "ITW", "PH", "CMI", "WM",
    "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "DOW", "DD", "NUE", "CTVA",
    "PLD", "AMT", "EQIX", "CCI", "SPG", "O", "PSA", "WELL", "DLR", "VICI",
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "IVV", "XLK", "XLF", "XLV",
    "XLE", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC", "TLT", "IEF",
    "SHY", "HYG", "LQD", "GLD", "SLV", "USO", "UNG", "EFA", "EEM", "VEA",
] * 2

CN_SCALE_UNIVERSE_300 = [
    "600519", "000858", "300750", "601318", "600036", "601899", "600276", "000333", "002594", "600900",
    "601888", "600030", "600887", "600309", "000651", "601166", "601398", "601857", "601088", "600028",
    "601012", "300760", "600438", "002415", "000002", "600000", "601668", "600048", "600031", "601919",
    "600690", "600585", "000568", "000725", "002475", "300059", "600050", "601766", "600104", "000063",
    "510300", "510500", "510050", "159919", "159915", "512100", "512880", "512000", "512660", "515700",
    "601288", "601328", "601988", "601939", "601818", "600016", "600837", "600958", "601995", "601211",
    "600919", "601229", "601688", "000001", "002142", "000895", "603288", "600809", "603369", "600763",
    "600436", "000963", "600196", "000661", "300015", "600150", "601390", "601669", "600019", "000708",
    "600010", "601600", "603799", "002460", "000792", "600111", "600362", "002371", "002230", "002241",
    "300124", "300274", "300408", "002236", "002027", "300014", "300122", "603501", "688981", "688111",
    "688012", "688036", "688008", "002129", "002812", "300450", "002459", "002466", "300037", "300207",
    "600406", "601877", "603806", "002050", "300347", "002001", "000538", "600085", "600079", "600332",
    "603259", "300759", "001979", "600606", "000069", "601601", "601628", "600999", "000776", "600109",
    "600941", "601728", "300413", "002555", "002602", "300251", "002517", "588000", "588080", "512170",
    "512690", "512010", "512400", "512480", "512760", "515050", "515790", "516160", "516970", "159995",
    "159928", "159901", "159949", "159967", "159865", "159845", "159857", "159755", "159766", "159819",
    "159920", "513050", "513100", "513500", "513330", "518880", "511010", "511260", "511880",
]

REQUIRED_METRICS = ["calibration_ece", "pinball_loss", "crps", "var_breach_rate", "walk_forward", "purged_cv"]


def parse_symbols(raw: str | None, default: list[str]) -> list[str]:
    if not raw:
        return default
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def symbol_market(symbol: str) -> str:
    return "cn" if symbol.isdigit() else "us"


def dataset_stats(dataset_path: Path) -> dict[str, Any]:
    payload = read_json(dataset_path / "dataset.json")
    samples = payload.get("samples", [])
    symbols = sorted({item["symbol"] for item in samples})
    splits: dict[str, int] = {}
    source_status: dict[str, int] = {}
    pit_violations = 0
    for sample in samples:
        splits[sample.get("split", "unknown")] = splits.get(sample.get("split", "unknown"), 0) + 1
        source_status[sample.get("sourceStatus", "unknown")] = source_status.get(sample.get("sourceStatus", "unknown"), 0) + 1
        audit = sample.get("pointInTimeAudit") or {}
        pit_violations += int(audit.get("futureLeakageCount") or 0)
    return {
        "datasetId": payload.get("datasetId"),
        "sampleCount": len(samples),
        "symbolCount": len(symbols),
        "symbols": symbols,
        "splits": splits,
        "sourceStatus": source_status,
        "pointInTimeFutureLeakageCount": pit_violations,
        "allowSynthetic": payload.get("allowSynthetic"),
        "smoke": payload.get("smoke"),
    }


def metric_gates(metrics: dict[str, Any], *, strict: bool) -> list[dict[str, Any]]:
    ece_limit = 0.12 if strict else 0.25
    pinball_limit = 0.2 if strict else 0.35
    gates = [
        {"name": "has_ece", "passed": "calibration_ece" in metrics, "value": metrics.get("calibration_ece"), "limit": "required"},
        {"name": "has_pinball", "passed": "pinball_loss" in metrics, "value": metrics.get("pinball_loss"), "limit": "required"},
        {"name": "has_crps", "passed": "crps" in metrics, "value": metrics.get("crps"), "limit": "required"},
        {"name": "has_var_breach_rate", "passed": "var_breach_rate" in metrics, "value": metrics.get("var_breach_rate"), "limit": "required"},
        {"name": "has_walk_forward", "passed": bool(metrics.get("walk_forward", {}).get("windowCount")), "value": metrics.get("walk_forward", {}).get("windowCount"), "limit": ">=1"},
        {"name": "has_purged_cv", "passed": bool(metrics.get("purged_cv", {}).get("foldCount")), "value": metrics.get("purged_cv", {}).get("foldCount"), "limit": ">=1"},
        {"name": "ece_limit", "passed": float(metrics.get("calibration_ece", 1.0)) <= ece_limit, "value": metrics.get("calibration_ece"), "limit": f"<={ece_limit}"},
        {"name": "pinball_limit", "passed": float(metrics.get("pinball_loss", 1.0)) <= pinball_limit, "value": metrics.get("pinball_loss"), "limit": f"<={pinball_limit}"},
    ]
    return gates


def dataset_gates(stats: dict[str, Any], *, min_symbols: int, min_samples: int) -> list[dict[str, Any]]:
    return [
        {"name": "min_symbols", "passed": stats["symbolCount"] >= min_symbols, "value": stats["symbolCount"], "limit": f">={min_symbols}"},
        {"name": "min_samples", "passed": stats["sampleCount"] >= min_samples, "value": stats["sampleCount"], "limit": f">={min_samples}"},
        {"name": "no_future_leakage", "passed": stats["pointInTimeFutureLeakageCount"] == 0, "value": stats["pointInTimeFutureLeakageCount"], "limit": "0"},
        {"name": "has_test_or_shadow", "passed": bool(stats["splits"].get("test") or stats["splits"].get("shadow")), "value": stats["splits"], "limit": "test/shadow required"},
    ]


def write_model_card(
    *,
    pipeline: str,
    model_id: str,
    dataset: dict[str, Any],
    trained: dict[str, Any],
    gates: list[dict[str, Any]],
    inference: list[dict[str, Any]],
) -> dict[str, Any]:
    metrics = trained.get("metrics", {})
    model_card = {
        "pipeline": pipeline,
        "modelId": model_id,
        "modelType": trained.get("modelType"),
        "createdAt": now_iso(),
        "dataset": dataset,
        "metrics": {key: metrics.get(key) for key in REQUIRED_METRICS + ["risk_regime_accuracy", "risk_regime_f1_macro", "sample_count"]},
        "judgeV2": metrics.get("judge_v2"),
        "registryStatus": trained.get("registry", {}).get("status"),
        "gates": gates,
        "passed": all(item["passed"] for item in gates),
        "inferencePreview": inference,
        "limitations": [
            "输出风险分布，不输出确定性买卖建议。",
            "sourceStatus=degraded 的训练结果只能作为 Demo 或工程验证。",
            "真实部署前必须扩大真实样本、复权处理、幸存者偏差说明和数据权限审查。",
        ],
    }
    write_json(artifact_path("models", model_id, "model_card.json"), model_card)
    return model_card


def deep_candidate_audit(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "status": "not_run",
            "summary": "Deep sequence candidates were not trained in this run.",
            "candidates": [],
        }
    audited = []
    for candidate in candidates:
        metrics = candidate.get("metrics", {})
        gates = [
            {
                "name": "trained",
                "passed": bool(candidate.get("ok")) and metrics.get("model_impl") != "torch_unavailable",
                "value": metrics.get("model_impl"),
                "limit": "torch candidate trained",
            },
            {
                "name": "has_out_of_sample_metrics",
                "passed": int(metrics.get("evaluated_sample_count") or 0) > 0,
                "value": metrics.get("evaluated_sample_count"),
                "limit": ">0",
            },
            {
                "name": "has_walk_forward",
                "passed": int(metrics.get("walk_forward", {}).get("windowCount") or 0) >= 1,
                "value": metrics.get("walk_forward", {}).get("windowCount"),
                "limit": ">=1",
            },
            {
                "name": "has_purged_cv",
                "passed": int(metrics.get("purged_cv", {}).get("foldCount") or 0) >= 1,
                "value": metrics.get("purged_cv", {}).get("foldCount"),
                "limit": ">=1",
            },
            {
                "name": "ece_observed",
                "passed": "calibration_ece" in metrics,
                "value": metrics.get("calibration_ece"),
                "limit": "required",
            },
            {
                "name": "pinball_observed",
                "passed": "pinball_loss" in metrics,
                "value": metrics.get("pinball_loss"),
                "limit": "required",
            },
            {
                "name": "crps_observed",
                "passed": "crps" in metrics,
                "value": metrics.get("crps"),
                "limit": "required",
            },
            {
                "name": "var_breach_reasonable",
                "passed": 0.01 <= float(metrics.get("var_breach_rate", 1.0)) <= 0.35,
                "value": metrics.get("var_breach_rate"),
                "limit": "0.01..0.35",
            },
        ]
        basic_pass = all(item["passed"] for item in gates)
        promotable = (
            basic_pass
            and float(metrics.get("calibration_ece", 1.0)) <= 0.12
            and float(metrics.get("pinball_loss", 1.0)) <= 0.2
            and float(metrics.get("crps", 1.0)) <= 0.4
            and 0.01 <= float(metrics.get("var_breach_rate", 1.0)) <= 0.35
            and int(metrics.get("walk_forward", {}).get("windowCount") or 0) >= 2
            and int(metrics.get("purged_cv", {}).get("foldCount") or 0) >= 3
        )
        audited.append(
            {
                "modelId": candidate.get("modelId"),
                "modelType": candidate.get("modelType"),
                "artifactPath": candidate.get("artifactPath"),
                "candidateStatus": "promotable_candidate" if promotable else "research_candidate" if basic_pass else "failed_candidate",
                "gates": gates,
                "metrics": {
                    "risk_regime_accuracy": metrics.get("risk_regime_accuracy"),
                    "risk_regime_f1_macro": metrics.get("risk_regime_f1_macro"),
                    "calibration_ece": metrics.get("calibration_ece"),
                    "pinball_loss": metrics.get("pinball_loss"),
                    "crps": metrics.get("crps"),
                    "var_breach_rate": metrics.get("var_breach_rate"),
                    "evaluated_sample_count": metrics.get("evaluated_sample_count"),
                    "walk_forward": metrics.get("walk_forward"),
                    "purged_cv": metrics.get("purged_cv"),
                },
            }
        )
    return {
        "status": "pass" if all(item["candidateStatus"] != "failed_candidate" for item in audited) else "fail",
        "summary": "Deep models are auxiliary candidates; only promotable candidates may enter production cards after human model-card review.",
        "candidates": audited,
    }


def write_manifest(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    manifest = {"runId": run_id, "createdAt": now_iso(), **payload}
    write_json(artifact_path("pipelines", run_id, "manifest.json"), manifest)
    return manifest
