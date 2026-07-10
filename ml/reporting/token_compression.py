from __future__ import annotations

import json
import math
from typing import Any


def estimate_tokens(value: Any) -> int:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if not text:
        return 0
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars / 4 + non_ascii_chars / 1.6))


def build_token_compression_report(
    *,
    symbol: str,
    raw_market_rows: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    document_analysis: dict[str, Any],
    ml_summary: dict[str, Any],
) -> dict[str, Any]:
    raw_inputs = {
        "marketRows": raw_market_rows,
        "evidenceClaims": [
            {
                "sourceType": item.get("sourceType"),
                "sourceName": item.get("sourceName"),
                "claim": item.get("claim"),
                "observedAt": item.get("observedAt"),
            }
            for item in evidence
        ],
        "documentBlocks": document_analysis.get("blockPreviews", []),
    }
    structured_summary = {
        "symbol": symbol,
        "evidenceCount": len(evidence),
        "sourceTypes": sorted({item.get("sourceType") for item in evidence}),
        "documentMetrics": document_analysis.get("metrics", []),
        "riskDistribution": ml_summary.get("riskDistribution"),
        "featureStoreAudit": ml_summary.get("featureStoreAudit"),
        "validationMetrics": ml_summary.get("validationMetrics"),
        "similarScenarioCount": ml_summary.get("similarScenarioCount"),
    }
    raw_breakdown = {key: estimate_tokens(value) for key, value in raw_inputs.items()}
    structured_breakdown = {key: estimate_tokens(value) for key, value in structured_summary.items()}
    raw_total = sum(raw_breakdown.values())
    structured_total = sum(structured_breakdown.values())
    reduction = 0.0 if raw_total == 0 else 1 - structured_total / raw_total
    consistency_checks = [
        {
            "name": "risk_regime_preserved",
            "passed": bool(ml_summary.get("riskRegime") and ml_summary.get("riskDistribution", {}).get("riskRegime")),
            "detail": "结构化摘要保留 riskRegime 和分布口径。",
        },
        {
            "name": "evidence_source_count_preserved",
            "passed": len(structured_summary["sourceTypes"]) >= 3,
            "detail": "结构化摘要保留主要证据类型，而不是只保留最终结论。",
        },
        {
            "name": "pit_and_calibration_preserved",
            "passed": bool(ml_summary.get("featureStoreAudit")) and bool(ml_summary.get("validationMetrics")),
            "detail": "结构化摘要保留点时审计和校准/回测指标。",
        },
    ]
    return {
        "symbol": symbol,
        "rawTokenEstimate": raw_total,
        "structuredTokenEstimate": structured_total,
        "tokenReductionPercent": round(reduction * 100, 2),
        "rawBreakdown": raw_breakdown,
        "structuredBreakdown": structured_breakdown,
        "conclusionConsistency": round(sum(1 for item in consistency_checks if item["passed"]) / len(consistency_checks), 4),
        "consistencyChecks": consistency_checks,
        "method": "character_token_estimate_for_demo",
        "summary": f"Agent 可读取结构化风险摘要替代原始长序列，估算 token 降低 {round(reduction * 100, 2)}%。",
    }
