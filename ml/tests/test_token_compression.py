from __future__ import annotations

from ml.reporting.token_compression import build_token_compression_report


def run() -> None:
    raw_rows = [{"trade_date": f"2024-01-{idx:02d}", "close_price": 100 + idx, "volume": 1000000 + idx} for idx in range(1, 20)]
    evidence = [
        {"sourceType": "market_data", "sourceName": "test", "claim": "market", "observedAt": "2024-01-20"},
        {"sourceType": "financial_report", "sourceName": "test", "claim": "financial", "observedAt": "2024-01-20"},
        {"sourceType": "model_inference", "sourceName": "test", "claim": "risk", "observedAt": "2024-01-20"},
    ]
    ml_summary = {
        "riskRegime": "high",
        "riskDistribution": {"riskRegime": "high"},
        "featureStoreAudit": {"ok": True},
        "validationMetrics": {"calibration_ece": 0.05},
        "similarScenarioCount": 3,
    }
    report = build_token_compression_report(
        symbol="TST",
        raw_market_rows=raw_rows,
        evidence=evidence,
        document_analysis={"metrics": [], "blockPreviews": [{"text": "long preview" * 20}]},
        ml_summary=ml_summary,
    )
    assert report["rawTokenEstimate"] > report["structuredTokenEstimate"]
    assert report["tokenReductionPercent"] > 0
    assert report["conclusionConsistency"] >= 0.66


if __name__ == "__main__":
    run()
    print("test_token_compression ok")
