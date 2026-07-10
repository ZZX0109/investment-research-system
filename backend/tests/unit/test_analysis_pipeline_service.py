from __future__ import annotations

from backend.analysis_pipeline_service import build_analysis_run_context, create_research_analysis_run


def build_source_meta(**kwargs):
    return {
        "mode": kwargs.get("mode", "demo"),
        "provider": kwargs["provider"],
        "as_of": kwargs["as_of"],
        "overrides": kwargs.get("overrides", []),
        "synthetic_ratio": kwargs.get("synthetic_ratio", 0.0),
    }


def base_inputs():
    return {
        "holding": {
            "symbol": "UNIT",
            "name": "Unit Test Asset",
            "market": "us",
            "observedAt": "2026-07-07T09:00:00Z",
        },
        "preference_label": "均衡模式",
        "risk_score": 67.5,
        "text": {"riskLabel": "中高风险", "riskLevel": "medium"},
        "evidence": [{"id": 2, "claim": "claim a"}, {"id": 3, "claim": "claim b"}],
        "analogies": [{"asOfDate": "2026-07-01", "maxDrawdown": -12.5}],
        "document_analysis": {"uploadedAt": "2026-07-07T08:00:00Z"},
        "ml_summary": {"modelId": "risk-model-v2"},
        "quality_gate": {
            "status": "HOLD",
            "reasons": ["证据不足", "模型置信度低"],
            "syntheticRatio": 0.4,
        },
        "audit": {"score": 61, "verdict": "needs work"},
        "reasoning_steps": [{"role": "Research Agent", "status": "done"}],
        "build_source_meta": build_source_meta,
    }


def create_inputs():
    return {**base_inputs(), "preference": "balanced"}


def test_build_analysis_run_context_freezes_snapshot_and_quality_gate():
    context = build_analysis_run_context(**base_inputs())

    assert context["summary"] == "Unit Test Asset 当前结论已降级为 HOLD，原因: 证据不足、模型置信度低。"
    assert context["modelVersion"] == "risk-model-v2"
    assert context["evidenceIds"] == [2, 3]
    assert context["inputSnapshot"]["holding"]["symbol"] == "UNIT"
    assert context["inputSnapshot"]["qualityGate"]["status"] == "HOLD"
    assert context["judgePayload"]["qualityGate"]["reasons"] == ["证据不足", "模型置信度低"]
    assert context["riskConclusion"] == {
        "riskLabel": "中高风险",
        "riskLevel": "medium",
        "riskScore": 67.5,
        "gateStatus": "HOLD",
    }
    assert context["sourceMeta"]["provider"] == "research_pipeline"
    assert context["sourceMeta"]["overrides"] == ["证据不足", "模型置信度低"]
    assert context["sourceMeta"]["synthetic_ratio"] == 0.4


def test_create_research_analysis_run_delegates_fixed_context_to_run_service():
    captured = {}

    def create_research_run(symbol, preference, risk_score, summary, **kwargs):
        captured.update(
            {
                "symbol": symbol,
                "preference": preference,
                "risk_score": risk_score,
                "summary": summary,
                **kwargs,
            }
        )
        return {
            "runId": "UNIT-balanced-run",
            "summary": summary,
            "riskScore": risk_score,
            "inputSnapshotHash": "hash",
            "modelVersion": kwargs["model_version"],
            "evidenceIds": kwargs["evidence_ids"],
            "judge": kwargs["judge_payload"],
            "riskConclusion": kwargs["risk_conclusion"],
            "sourceMeta": kwargs["source_meta"],
        }

    result = create_research_analysis_run(create_research_run=create_research_run, **create_inputs())

    assert result["run"]["runId"] == "UNIT-balanced-run"
    assert captured["input_snapshot"]["qualityGate"]["status"] == "HOLD"
    assert captured["model_version"] == "risk-model-v2"
    assert captured["evidence_ids"] == [2, 3]
    assert captured["judge_payload"]["audit"]["score"] == 61
    assert captured["risk_conclusion"]["gateStatus"] == "HOLD"
    assert captured["source_meta"]["synthetic_ratio"] == 0.4
