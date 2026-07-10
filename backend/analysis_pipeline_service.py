from __future__ import annotations

from typing import Any, Callable

from .schemas import AnalysisPipelineRunContext


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def build_run_summary(
    *,
    holding_name: str,
    preference_label: str,
    risk_score: float,
    quality_gate: dict[str, Any],
) -> str:
    if quality_gate["status"] in {"PASS", "WARN"}:
        return f"{holding_name} 在{preference_label}下的风险评分为 {risk_score}。"
    return f"{holding_name} 当前结论已降级为 {quality_gate['status']}，原因: {'、'.join(quality_gate['reasons'])}。"


def build_analysis_run_context(
    *,
    holding: dict[str, Any],
    preference_label: str,
    risk_score: float,
    text: dict[str, Any],
    evidence: list[dict[str, Any]],
    analogies: list[dict[str, Any]],
    document_analysis: dict[str, Any],
    ml_summary: dict[str, Any],
    quality_gate: dict[str, Any],
    audit: dict[str, Any],
    reasoning_steps: list[dict[str, Any]],
    build_source_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    source_meta = build_source_meta(
        provider="research_pipeline",
        as_of=document_analysis.get("uploadedAt") or holding.get("observedAt"),
        overrides=quality_gate["reasons"] if quality_gate["status"] != "PASS" else [],
        synthetic_ratio=quality_gate["syntheticRatio"],
    )
    context = AnalysisPipelineRunContext(
        summary=build_run_summary(
            holding_name=holding["name"],
            preference_label=preference_label,
            risk_score=risk_score,
            quality_gate=quality_gate,
        ),
        inputSnapshot={
            "holding": holding,
            "evidence": evidence,
            "analogies": analogies,
            "documentAnalysis": document_analysis,
            "mlRiskSummary": ml_summary,
            "qualityGate": quality_gate,
        },
        modelVersion=ml_summary.get("modelId") or "missing_model",
        evidenceIds=[int(item["id"]) for item in evidence],
        reasoningSteps=reasoning_steps,
        judgePayload={"audit": audit, "qualityGate": quality_gate},
        riskConclusion={
            "riskLabel": text["riskLabel"],
            "riskLevel": text["riskLevel"],
            "riskScore": risk_score,
            "gateStatus": quality_gate["status"],
        },
        sourceMeta=source_meta,
    )
    return dump_model(context)


def create_research_analysis_run(
    *,
    holding: dict[str, Any],
    preference: str,
    preference_label: str,
    risk_score: float,
    text: dict[str, Any],
    evidence: list[dict[str, Any]],
    analogies: list[dict[str, Any]],
    document_analysis: dict[str, Any],
    ml_summary: dict[str, Any],
    quality_gate: dict[str, Any],
    audit: dict[str, Any],
    reasoning_steps: list[dict[str, Any]],
    build_source_meta: Callable[..., dict[str, Any]],
    create_research_run: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    context = build_analysis_run_context(
        holding=holding,
        preference_label=preference_label,
        risk_score=risk_score,
        text=text,
        evidence=evidence,
        analogies=analogies,
        document_analysis=document_analysis,
        ml_summary=ml_summary,
        quality_gate=quality_gate,
        audit=audit,
        reasoning_steps=reasoning_steps,
        build_source_meta=build_source_meta,
    )
    run = create_research_run(
        holding["symbol"],
        preference,
        risk_score,
        context["summary"],
        input_snapshot=context["inputSnapshot"],
        model_version=context["modelVersion"],
        evidence_ids=context["evidenceIds"],
        reasoning_steps=context["reasoningSteps"],
        judge_payload=context["judgePayload"],
        risk_conclusion=context["riskConclusion"],
        source_meta=context["sourceMeta"],
    )
    return {"run": run, "context": context, "sourceMeta": context["sourceMeta"]}
