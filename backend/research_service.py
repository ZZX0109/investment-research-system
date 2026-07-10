from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from .analysis_pipeline_service import create_research_analysis_run


def build_research_payload(
    *,
    symbol: str,
    preference: str,
    user_id: int | None,
    get_user_holdings: Callable[[int | None], list[dict[str, Any]]],
    get_default_holdings: Callable[[], list[dict[str, Any]]],
    research_text: Callable[[str, str, str, str], dict[str, Any]],
    get_evidence: Callable[[str], list[dict[str, Any]]],
    get_historical_analogies: Callable[[str], list[dict[str, Any]]],
    latest_document_analysis: Callable[[str], dict[str, Any]],
    latest_ml_risk_summary: Callable[[str], dict[str, Any]],
    token_compression_report: Callable[[str, list[dict[str, Any]], dict[str, Any], dict[str, Any]], dict[str, Any]],
    build_evidence_graph: Callable[..., dict[str, Any]],
    research_quality_audit: Callable[..., dict[str, Any]],
    report_revision_loop: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    build_quality_gate: Callable[..., dict[str, Any]],
    compute_risk_score: Callable[[str, list[dict[str, Any]], list[dict[str, Any]]], float],
    previous_run_delta: Callable[[str, float], dict[str, Any]],
    create_research_run: Callable[..., dict[str, Any]],
    log_research_toolchain: Callable[..., None],
    preference_copy: Callable[[str], dict[str, Any]],
    agent_workflow: Callable[..., list[dict[str, Any]]],
    get_tool_invocations: Callable[[str], list[dict[str, Any]]],
    condition_alignment: Callable[[str, list[dict[str, Any]], str], dict[str, Any]],
    preference_weights: Callable[[str], list[dict[str, Any]]],
    report_settings: Callable[[], dict[str, Any]],
    recent_runs: Callable[[str], list[dict[str, Any]]],
    debate_payload: Callable[[str, str, list[dict[str, Any]], dict[str, Any]], dict[str, Any]],
    observation_checklist: Callable[[str, str], list[dict[str, Any]]],
    get_price_points: Callable[[str, int], list[dict[str, Any]]],
    get_experience_history: Callable[[str | None], list[dict[str, Any]]],
    build_source_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    symbol = symbol.upper()
    holdings = get_user_holdings(user_id) if user_id is not None else get_default_holdings()
    if not holdings:
        raise HTTPException(status_code=400, detail="No holdings. Complete onboarding first.")

    holding = next((item for item in holdings if item["symbol"].upper() == symbol), None)
    if holding is None:
        available = ", ".join(item["symbol"] for item in holdings)
        raise HTTPException(status_code=404, detail=f"{symbol} is not in the current portfolio or watchlist. Available symbols: {available}")

    text = research_text(holding["symbol"], holding["name"], holding["sector"], preference)
    evidence = get_evidence(holding["symbol"])
    analogies = get_historical_analogies(holding["symbol"])
    document_analysis = latest_document_analysis(holding["symbol"])
    ml_summary = latest_ml_risk_summary(holding["symbol"])
    compression_report = token_compression_report(holding["symbol"], evidence, document_analysis, ml_summary)
    base_evidence_graph = build_evidence_graph(evidence, holding, document_analysis, analogies)
    audit = research_quality_audit(
        evidence,
        holding["symbol"],
        holding["market"],
        document_analysis,
        analogies,
        has_bear_case=True,
        claim_graph=base_evidence_graph,
        ml_summary=ml_summary,
        token_report=compression_report,
    )
    evidence_graph = build_evidence_graph(evidence, holding, document_analysis, analogies, audit)
    quality_gate = build_quality_gate(
        evidence=evidence,
        analogies=analogies,
        audit=audit,
        ml_summary=ml_summary,
    )
    revision_loop = report_revision_loop(audit, evidence_graph)
    if quality_gate["status"] in {"HOLD", "BLOCK"}:
        revision_loop = {
            **revision_loop,
            "finalStatus": "data_insufficient",
            "qualityGateStatus": quality_gate["status"],
            "judgeVerdict": f"{revision_loop['judgeVerdict']} / {quality_gate['status']}",
            "revisedSummary": quality_gate["summary"],
            "blockedBy": [*revision_loop["blockedBy"], *quality_gate["reasons"]],
        }
    risk_score = compute_risk_score(text["riskLevel"], evidence, analogies)
    version_delta = previous_run_delta(holding["symbol"], risk_score)
    reasoning_steps = agent_workflow(holding["symbol"], preference, document_analysis, analogies, audit, ml_summary)
    profile = preference_copy(preference)
    analysis_run = create_research_analysis_run(
        holding=holding,
        preference=preference,
        preference_label=profile["label"],
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
        create_research_run=create_research_run,
    )
    run = analysis_run["run"]
    payload_source_meta = analysis_run["sourceMeta"]
    log_research_toolchain(
        run["runId"],
        holding,
        evidence,
        document_analysis,
        analogies,
        audit,
        evidence_graph,
        revision_loop,
        version_delta,
        ml_summary,
    )
    document_blocks = [
        *text["documentBlocks"],
        {
            "title": "审计修订稿",
            "text": revision_loop["revisedSummary"],
        },
    ]
    return {
        "symbol": holding["symbol"],
        "name": holding["name"],
        "market": holding["market"],
        "riskScore": risk_score,
        "summary": run["summary"],
        "sourceMeta": payload_source_meta,
        **text,
        "documentBlocks": document_blocks,
        "run": run,
        "agentWorkflow": reasoning_steps,
        "mlRiskSummary": ml_summary,
        "mlSummary": ml_summary,
        "tokenCompressionReport": compression_report,
        "toolCalls": get_tool_invocations(run["runId"]),
        "documentAnalysis": document_analysis,
        "audit": audit,
        "evidenceAudit": audit,
        "qualityGate": quality_gate,
        "evidenceGraph": evidence_graph,
        "revision": revision_loop,
        "reportRevisionLoop": revision_loop,
        "conditionAlignment": condition_alignment(holding["symbol"], analogies, preference),
        "preferenceWeights": preference_weights(preference),
        "reportSettings": report_settings(),
        "reportVersions": {"current": run, "delta": version_delta, "recentRuns": recent_runs(holding["symbol"])},
        "debate": debate_payload(holding["symbol"], holding["name"], evidence, audit),
        "observationChecklist": observation_checklist(holding["symbol"], preference),
        "evidence": evidence,
        "historicalAnalogies": analogies,
        "priceSeries": get_price_points(holding["symbol"], limit=120),
        "experienceHistory": get_experience_history(holding["symbol"]),
    }
