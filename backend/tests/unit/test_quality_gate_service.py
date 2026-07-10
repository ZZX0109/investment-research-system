from __future__ import annotations

from backend.research_domain_service import build_quality_gate_payload


def test_quality_gate_blocks_sparse_stale_synthetic_low_confidence_run():
    evidence = [
        {
            "sourceType": "market_data",
            "isExpired": True,
            "claim": "synthetic demo placeholder price path",
            "sourceName": "synthetic_demo_price_path",
        }
    ]
    analogies = [{"sourceMeta": {"synthetic_ratio": 1.0}}]
    gate = build_quality_gate_payload(
        evidence=evidence,
        analogies=analogies,
        audit={"score": 42},
        ml_summary={"confidence": 0.33, "modelStatus": "stale"},
        contains_demo_placeholder=lambda value: "synthetic" in str(value or "").lower() or "placeholder" in str(value or "").lower(),
    )

    assert gate["status"] == "BLOCK"
    assert set(gate["reasons"]) >= {"证据不足", "数据过旧", "synthetic占比过高", "模型置信度低"}
    assert gate["syntheticRatio"] == 1.0


def test_quality_gate_warns_when_required_sources_are_present_and_fresh():
    source_types = ["market_data", "financial_report", "disclosure", "news_event", "historical_analogy", "model_inference"]
    evidence = [
        {
            "sourceType": source_type,
            "isExpired": False,
            "claim": f"{source_type} evidence",
            "sourceName": "real_provider",
        }
        for source_type in source_types
    ]
    gate = build_quality_gate_payload(
        evidence=evidence,
        analogies=[{"sourceMeta": {"synthetic_ratio": 0.0}}],
        audit={"score": 86},
        ml_summary={"confidence": 0.72, "modelStatus": "valid"},
        contains_demo_placeholder=lambda value: False,
    )

    assert gate["status"] == "PASS"
    assert gate["reasons"] == []
    assert gate["gatingReasons"] == []
    assert gate["missingTypes"] == []
