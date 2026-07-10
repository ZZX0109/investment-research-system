from __future__ import annotations

import json
from typing import Any, Callable, Literal


EvidenceType = Literal["market_data", "financial_report", "disclosure", "news_event", "historical_analogy", "model_inference"]


def build_research_quality_audit(
    *,
    evidence: list[dict[str, Any]],
    symbol: str,
    market: str,
    document_analysis: dict[str, Any],
    analogies: list[dict[str, Any]],
    has_bear_case: bool,
    claim_graph: dict[str, Any] | None,
    ml_summary: dict[str, Any] | None,
    token_report: dict[str, Any] | None,
    contains_demo_placeholder: Callable[[str | None], bool],
    is_structured_metric: Callable[[dict[str, Any]], bool],
    has_personalized_advice_violation: Callable[[list[str]], bool],
    authority_sources: Callable[[str, str], list[dict[str, Any]]],
) -> dict[str, Any]:
    expired = [item for item in evidence if item["isExpired"]]
    present_types = {item["sourceType"] for item in evidence}
    required = {"market_data", "financial_report", "disclosure", "news_event", "historical_analogy", "model_inference"}
    missing = sorted(required - present_types)
    placeholder_evidence = [
        item
        for item in evidence
        if contains_demo_placeholder(item.get("claim")) or contains_demo_placeholder(item.get("sourceName"))
    ]
    metrics = document_analysis.get("metrics", [])
    structured_metrics = [item for item in metrics if is_structured_metric(item)]
    financial_metric_sources_ok = bool(structured_metrics) and document_analysis.get("sourceType") != "demo_cache"
    backtest_warning_ok = bool(analogies) and all(
        any(keyword in item.get("note", "") for keyword in ["asOfDate", "样本外", "非预测", "风险分布", "截断"])
        for item in analogies
    )
    fact_inference_ok = all((item["sourceType"] == "model_inference") == item["isModelInferred"] for item in evidence)
    disclosure_ok = any(
        item["sourceType"] == "disclosure"
        and "刷新成功" in item.get("claim", "")
        and float(item.get("confidence", 0)) >= 0.7
        for item in evidence
    )
    advice_boundary_ok = not has_personalized_advice_violation(
        [item.get("claim", "") for item in evidence]
        + [item.get("sourceName", "") for item in evidence]
        + [item.get("claim", "") for item in (claim_graph or {}).get("claims", [])]
    )
    unsupported_claims = [
        item for item in (claim_graph or {}).get("claims", [])
        if item.get("status") in {"unsupported", "contested"}
    ]
    ml_summary = ml_summary or {}
    token_report = token_report or {}
    feature_store_audit = ml_summary.get("featureStoreAudit", {})
    validation_metrics = ml_summary.get("validationMetrics", {})
    risk_distribution = ml_summary.get("riskDistribution", {})
    no_future_data_ok = bool(feature_store_audit.get("ok")) and int(feature_store_audit.get("futureLeakageCount") or 0) == 0
    out_of_sample_ok = bool(validation_metrics.get("walk_forward", {}).get("windowCount")) and bool(validation_metrics.get("purged_cv", {}).get("foldCount"))
    calibration_metrics_ok = all(key in validation_metrics for key in ["calibration_ece", "pinball_loss", "crps", "var_breach_rate"])
    risk_distribution_ok = bool(risk_distribution.get("drawdownQuantiles")) and bool(risk_distribution.get("varBreach"))
    source_attribution_ok = all(item.get("sourceName") and item.get("observedAt") and item.get("sourceType") for item in evidence)
    deterministic_terms = ["未来会涨", "未来会跌", "一定上涨", "一定下跌", "确定上涨", "确定下跌", "必然上涨", "必然下跌"]
    probabilistic_language_ok = not any(
        term in text
        for text in [item.get("claim", "") for item in evidence] + [item.get("claim", "") for item in (claim_graph or {}).get("claims", [])]
        for term in deterministic_terms
    )
    token_compression_ok = bool(token_report) and float(token_report.get("tokenReductionPercent", 0)) > 0 and float(token_report.get("conclusionConsistency", 0)) >= 0.66
    ml_quality_ok = (
        ml_summary.get("modelStatus") == "valid"
        and ml_summary.get("calibrationStatus") == "valid"
        and bool(ml_summary.get("modelId"))
        and no_future_data_ok
        and out_of_sample_ok
        and calibration_metrics_ok
        and risk_distribution_ok
    )
    dimensions = [
        {
            "key": "evidence_sufficiency",
            "label": "证据是否充分",
            "passed": not missing and len(evidence) >= 5 and len(placeholder_evidence) <= 1,
            "severity": "high",
            "detail": "证据需覆盖行情、财报、新闻、历史类比、模型推断，且不能主要依赖 demo placeholder。" if missing or len(placeholder_evidence) > 1 else "证据类型覆盖完整，且占位证据比例可控。",
        },
        {
            "key": "freshness",
            "label": "信息是否过期",
            "passed": len(expired) == 0,
            "severity": "high",
            "detail": f"{len(expired)} 条证据已过有效期，需要刷新后再生成推断。" if expired else "证据仍在有效期内。",
        },
        {
            "key": "financial_metric_sources",
            "label": "财务指标是否有来源",
            "passed": financial_metric_sources_ok,
            "severity": "medium",
            "detail": "财务指标需要来自上传财报/公告的结构化表格块，demo_cache、候选文本或 demo table 不能算作事实来源。" if not financial_metric_sources_ok else f"{len(structured_metrics)} 个财务指标已绑定上传文档中的结构化表格块。",
        },
        {
            "key": "authority_disclosure",
            "label": "是否核验权威公告/披露",
            "passed": disclosure_ok,
            "severity": "high",
            "detail": "必须从 SEC/巨潮等权威披露源获得有效公告 evidence，检索入口或失败记录不能算作已核验事实。" if not disclosure_ok else "已从权威披露源获得有效公告/filing evidence。",
        },
        {
            "key": "backtest_out_of_sample_warning",
            "label": "策略回测是否有样本外风险提示",
            "passed": backtest_warning_ok,
            "severity": "medium",
            "detail": "历史类比必须说明 asOfDate 截断、非预测属性和样本外风险，避免把回测包装成预测。" if not backtest_warning_ok else "历史类比已说明 asOfDate 截断、非预测属性和样本外风险。",
        },
        {
            "key": "fact_inference_boundary",
            "label": "结论是否混淆事实和推断",
            "passed": fact_inference_ok,
            "severity": "high",
            "detail": "事实证据与模型推断必须拆分记录，模型推断不能伪装成行情、财报或新闻事实。" if not fact_inference_ok else "事实证据与模型推断已通过 sourceType 和 isModelInferred 拆开。",
        },
        {
            "key": "bear_case",
            "label": "是否缺少反方观点",
            "passed": has_bear_case,
            "severity": "medium",
            "detail": "研究报告必须包含反方观点、推翻条件或风险审稿意见。" if not has_bear_case else "报告包含反方观点和推翻条件。",
        },
        {
            "key": "personalized_advice_boundary",
            "label": "是否出现个性化荐股越界",
            "passed": advice_boundary_ok,
            "severity": "high",
            "detail": "报告或证据链出现买入/卖出/加减仓/目标价等个性化荐股表达，必须降级并改写为研究观察项。" if not advice_boundary_ok else "报告边界保持在研究质量、证据状态和观察项，不输出个性化买卖建议。",
        },
        {
            "key": "claim_level_support",
            "label": "结论是否有 claim 级证据图谱",
            "passed": bool(claim_graph) and len(unsupported_claims) == 0,
            "severity": "high",
            "detail": f"{len(unsupported_claims)} 条 claim 缺少有效支撑或被反证，报告必须降级或补证据。" if unsupported_claims else "每条核心 claim 都已绑定支持/反驳证据、派生指标和过期状态。",
        },
        {
            "key": "ml_model_quality",
            "label": "时序模型是否样本外验证与校准",
            "passed": ml_quality_ok,
            "severity": "medium",
            "detail": "模型必须有 modelId、有效期、校准状态和样本外验证记录；缺失或 stale 时不能生成模型结论。" if not ml_quality_ok else "模型推断带有 modelId、有效期和 valid calibration 状态。",
        },
        {
            "key": "pit_feature_store",
            "label": "是否通过 Point-in-Time Feature Store 检查",
            "passed": no_future_data_ok,
            "severity": "high",
            "detail": f"Feature Store 必须为每个字段记录 asOfDate/source/availableAt/revisionId；当前未来函数违规 {feature_store_audit.get('futureLeakageCount', 'unknown')} 条。" if not no_future_data_ok else f"{feature_store_audit.get('checkedFieldCount', 0)} 个字段通过点时元数据和未来函数检查。",
        },
        {
            "key": "risk_distribution_engine",
            "label": "是否输出风险分布而非涨跌预测",
            "passed": risk_distribution_ok,
            "severity": "high",
            "detail": "必须输出 1周/1月回撤分布、波动率分位、高风险 regime 和 VaR breach，不能只输出单点涨跌方向。" if not risk_distribution_ok else "已输出 drawdown quantiles、volatility quantiles、high-risk regime 和 VaR breach。",
        },
        {
            "key": "calibration_backtest_validator",
            "label": "是否完成校准与回测验证",
            "passed": out_of_sample_ok and calibration_metrics_ok,
            "severity": "high",
            "detail": "必须包含 ECE、pinball loss、CRPS、VaR breach rate、walk-forward 和 purged CV 结果。" if not (out_of_sample_ok and calibration_metrics_ok) else "校准/回测指标覆盖 ECE、pinball loss、CRPS、VaR breach、walk-forward 和 purged CV。",
        },
        {
            "key": "token_compression_report",
            "label": "是否量化 Agent token 压缩",
            "passed": token_compression_ok,
            "severity": "medium",
            "detail": "需要量化 raw 输入 token、结构化摘要 token、压缩率和结论一致性。" if not token_compression_ok else f"估算 token 降低 {token_report.get('tokenReductionPercent')}%，一致性 {token_report.get('conclusionConsistency')}。",
        },
        {
            "key": "source_attribution_v2",
            "label": "Judge v2 是否检查引用来源",
            "passed": source_attribution_ok,
            "severity": "high",
            "detail": "每条证据必须有 sourceType、sourceName 和 observedAt。" if not source_attribution_ok else "每条证据均带来源类型、来源名称和观察时间。",
        },
        {
            "key": "probabilistic_language_v2",
            "label": "Judge v2 是否禁止确定性预测表达",
            "passed": probabilistic_language_ok,
            "severity": "high",
            "detail": "风险概率不能表述为确定涨跌，必须改写成风险分布或观察项。" if not probabilistic_language_ok else "未发现把概率风险包装成确定涨跌的表达。",
        },
    ]
    penalty_by_severity = {"high": 18, "medium": 11, "low": 5}
    failed = [item for item in dimensions if not item["passed"]]
    findings = [{"severity": item["severity"], "title": item["label"], "detail": item["detail"]} for item in failed]
    if not findings:
        findings.append({"severity": "low", "title": "研究质量审查通过", "detail": "这份研究没有被 Judge 发现关键严谨性缺口，但仍不构成买卖建议。"})
    score = max(0, 100 - sum(penalty_by_severity[item["severity"]] for item in failed))
    return {
        "score": score,
        "judgeVersion": "v2",
        "verdict": "研究质量较严谨，可辅助继续研究" if score >= 80 else "研究质量需补强后再用于决策讨论" if score >= 60 else "研究质量不足，先补证据",
        "scope": "Research Quality Judge 只评价研究是否严谨、证据是否支撑结论，不评价这只股票是否值得买。",
        "dimensions": dimensions,
        "findings": findings,
        "authoritySources": authority_sources(symbol, market),
        "v2Checks": {
            "noFutureData": no_future_data_ok,
            "outOfSampleValidation": out_of_sample_ok,
            "calibration": calibration_metrics_ok,
            "sourceAttribution": source_attribution_ok,
            "probabilisticLanguage": probabilistic_language_ok,
            "bearCase": has_bear_case,
        },
        "checks": [{"name": item["label"], "passed": item["passed"]} for item in dimensions],
    }


def build_quality_gate_payload(
    *,
    evidence: list[dict[str, Any]],
    analogies: list[dict[str, Any]],
    audit: dict[str, Any],
    ml_summary: dict[str, Any],
    contains_demo_placeholder: Callable[[str | None], bool],
) -> dict[str, Any]:
    expired_count = sum(1 for item in evidence if item["isExpired"])
    missing_types = sorted(
        {"market_data", "financial_report", "disclosure", "news_event", "historical_analogy", "model_inference"}
        - {item["sourceType"] for item in evidence}
    )
    stale_data = expired_count > 0
    model_confidence = float(ml_summary.get("confidence") or 0)
    low_confidence = model_confidence < 0.55 or ml_summary.get("modelStatus") != "valid"
    synthetic_evidence = sum(
        1
        for item in evidence
        if contains_demo_placeholder(item.get("claim")) or contains_demo_placeholder(item.get("sourceName"))
    )
    synthetic_analogies = sum(1 for item in analogies if item.get("sourceMeta", {}).get("synthetic_ratio", 0) >= 1)
    denominator = max(1, len(evidence) + len(analogies))
    synthetic_ratio = round((synthetic_evidence + synthetic_analogies) / denominator, 4)
    reasons: list[str] = []
    if len(evidence) < 3:
        reasons.append("证据不足")
    if missing_types:
        reasons.append("关键证据缺失")
    if audit.get("score", 0) < 60:
        reasons.append("证据质量不足")
    if stale_data:
        reasons.append("数据过旧")
    if synthetic_ratio > 0.5:
        reasons.append("synthetic占比过高")
    if low_confidence:
        reasons.append("模型置信度低")
    status = "PASS"
    if reasons:
        status = "WARN"
    if missing_types or stale_data or synthetic_ratio > 0.5 or model_confidence < 0.55 or ml_summary.get("modelStatus") != "valid":
        status = "HOLD"
    if synthetic_ratio > 0.8 or model_confidence < 0.35:
        status = "BLOCK"
    summary = {
        "PASS": "质量门禁通过。",
        "WARN": "允许继续研究，但必须展示边界。",
        "HOLD": "结论自动降级为观察/等待刷新。",
        "BLOCK": "禁止输出投资结论，先补证据或更换数据源。",
    }[status]
    return {
        "status": status,
        "reasons": reasons,
        "gatingReasons": reasons,
        "expiredEvidenceCount": expired_count,
        "missingTypes": missing_types,
        "syntheticRatio": synthetic_ratio,
        "modelConfidence": round(model_confidence, 4),
        "summary": summary,
    }


def evidence_ids_by_type(evidence: list[dict[str, Any]], source_type: EvidenceType) -> list[int]:
    return [int(item["id"]) for item in evidence if item["sourceType"] == source_type]


def build_evidence_graph_payload(
    *,
    evidence: list[dict[str, Any]],
    holding: dict[str, Any],
    document_analysis: dict[str, Any],
    analogies: list[dict[str, Any]],
    audit: dict[str, Any] | None,
    is_structured_metric: Callable[[dict[str, Any]], bool],
    contains_demo_placeholder: Callable[[str | None], bool],
    synthetic_history_source: str,
) -> dict[str, Any]:
    market_ids = evidence_ids_by_type(evidence, "market_data")
    financial_ids = evidence_ids_by_type(evidence, "financial_report")
    disclosure_ids = evidence_ids_by_type(evidence, "disclosure")
    news_ids = evidence_ids_by_type(evidence, "news_event")
    analogy_ids = evidence_ids_by_type(evidence, "historical_analogy")
    inference_ids = evidence_ids_by_type(evidence, "model_inference")
    expired_ids = [int(item["id"]) for item in evidence if item["isExpired"]]
    real_document = document_analysis.get("sourceType") != "demo_cache"
    real_metrics = [item for item in document_analysis.get("metrics", []) if is_structured_metric(item)]
    placeholder_news = any(
        contains_demo_placeholder(item.get("claim")) or contains_demo_placeholder(item.get("sourceName"))
        or "刷新失败" in item.get("claim", "")
        or float(item.get("confidence", 0)) < 0.5
        for item in evidence
        if item["sourceType"] == "news_event"
    )
    synthetic_analogies = any(synthetic_history_source in item.get("dataSource", "") for item in analogies)
    disclosure_ok = any(
        item["sourceType"] == "disclosure"
        and "刷新成功" in item.get("claim", "")
        and float(item.get("confidence", 0)) >= 0.7
        for item in evidence
    )
    judge_score = audit.get("score") if audit else None
    claims = [
        {
            "id": "market_today_pnl",
            "title": "今日收益口径",
            "claim": f"{holding['symbol']} 的今日收益只能由有效行情快照和持仓份额计算得出。",
            "status": "supported" if holding.get("dataStatus") == "live" and market_ids else "contested",
            "supportingEvidenceIds": market_ids if holding.get("dataStatus") == "live" else [],
            "rebuttingEvidenceIds": [] if holding.get("dataStatus") == "live" else market_ids,
            "derivedMetrics": ["marketValue", "dayChange", "todayPnl"],
            "dependsOnExpiredEvidenceIds": [item for item in expired_ids if item in market_ids],
            "judgeNote": "live 行情可支撑收益计算。" if holding.get("dataStatus") == "live" else "当前行情为 fallback_cost_basis，不能当作实时价格事实。",
        },
        {
            "id": "financial_quality",
            "title": "财务指标来源",
            "claim": "财务指标必须先有权威 filing/公告 evidence，再由上传文档的结构化表格块计算，不能由 LLM 心算。",
            "status": "supported" if disclosure_ok and real_document and real_metrics else "contested",
            "supportingEvidenceIds": [*disclosure_ids, *financial_ids] if disclosure_ok and real_document and real_metrics else disclosure_ids if disclosure_ok else [],
            "rebuttingEvidenceIds": [] if disclosure_ok and real_document and real_metrics else financial_ids,
            "derivedMetrics": [item.get("metric_name", "") for item in real_metrics] or ["metrics_pending"],
            "dependsOnExpiredEvidenceIds": [item for item in expired_ids if item in financial_ids],
            "judgeNote": "财务指标已绑定权威 filing 与结构化来源。" if disclosure_ok and real_document and real_metrics else "当前缺少权威 filing 或结构化表格数值，报告需降级为数据不足。",
        },
        {
            "id": "authority_disclosure_check",
            "title": "权威公告核验",
            "claim": "公告、财报和重大事件必须有 SEC/巨潮/交易所等权威披露 evidence。",
            "status": "supported" if disclosure_ok else "contested",
            "supportingEvidenceIds": disclosure_ids if disclosure_ok else [],
            "rebuttingEvidenceIds": [] if disclosure_ok else disclosure_ids,
            "derivedMetrics": ["filingDate", "formType", "authoritySource"],
            "dependsOnExpiredEvidenceIds": [item for item in expired_ids if item in disclosure_ids],
            "judgeNote": "权威披露已核验。" if disclosure_ok else "当前只有披露入口或失败记录，不能当作已核验公告事实。",
        },
        {
            "id": "news_event_driver",
            "title": "新闻事件解释",
            "claim": "新闻只能解释风险上下文，必须有 24 小时内有效来源。",
            "status": "supported" if news_ids and not placeholder_news else "contested",
            "supportingEvidenceIds": news_ids if news_ids and not placeholder_news else [],
            "rebuttingEvidenceIds": [] if news_ids and not placeholder_news else news_ids,
            "derivedMetrics": ["event_tone", "freshness_window"],
            "dependsOnExpiredEvidenceIds": [item for item in expired_ids if item in news_ids],
            "judgeNote": "新闻源有效。" if news_ids and not placeholder_news else "新闻仍是占位、失败或低置信度，不能作为涨跌归因事实。",
        },
        {
            "id": "historical_analogy_scope",
            "title": "历史类比边界",
            "claim": "历史类比只展示风险分布，不输出预测，且必须按 asOfDate 截断。",
            "status": "contested" if synthetic_analogies else "supported",
            "supportingEvidenceIds": analogy_ids,
            "rebuttingEvidenceIds": analogy_ids if synthetic_analogies else [],
            "derivedMetrics": ["return1w", "return1m", "return3m", "maxDrawdown"],
            "dependsOnExpiredEvidenceIds": [item for item in expired_ids if item in analogy_ids],
            "judgeNote": "真实历史源可用于类比。" if not synthetic_analogies else "历史价格来自 synthetic_demo_price_path，只能用于 UI 演示。",
        },
        {
            "id": "report_conclusion_boundary",
            "title": "报告结论边界",
            "claim": "报告只能给研究质量和观察建议，不能输出个性化荐股或确定性买卖结论。",
            "status": "supported" if (judge_score or 0) >= 80 and not expired_ids else "contested" if audit else "pending",
            "supportingEvidenceIds": inference_ids if (judge_score or 0) >= 80 and not expired_ids else [],
            "rebuttingEvidenceIds": [*inference_ids, *expired_ids] if audit and ((judge_score or 0) < 80 or expired_ids) else [],
            "derivedMetrics": ["judgeScore", "riskScore", "verdict"],
            "dependsOnExpiredEvidenceIds": expired_ids,
            "judgeNote": (f"{audit['verdict']}；存在过期依赖证据，模型推断必须失效或重跑。" if expired_ids else audit["verdict"]) if audit else "等待 Judge 审稿。",
        },
    ]
    edges = []
    for claim in claims:
        for evidence_id in claim["supportingEvidenceIds"]:
            edges.append({"from": f"evidence:{evidence_id}", "to": f"claim:{claim['id']}", "relation": "supports", "label": "支持"})
        for evidence_id in claim["rebuttingEvidenceIds"]:
            edges.append({"from": f"evidence:{evidence_id}", "to": f"claim:{claim['id']}", "relation": "rebuts", "label": "反驳/降级"})
        for metric in claim["derivedMetrics"]:
            edges.append({"from": f"metric:{metric}", "to": f"claim:{claim['id']}", "relation": "derived", "label": "计算派生"})
    contested = sum(1 for item in claims if item["status"] != "supported")
    return {
        "summary": f"{len(claims)} 条核心 claim，{contested} 条需要补证据或降级。",
        "claims": claims,
        "edges": edges,
        "expiredEvidenceIds": expired_ids,
    }


def build_log_research_toolchain(
    *,
    run_id: str,
    holding: dict[str, Any],
    evidence: list[dict[str, Any]],
    document_analysis: dict[str, Any],
    analogies: list[dict[str, Any]],
    audit: dict[str, Any],
    evidence_graph: dict[str, Any],
    revision_loop: dict[str, Any],
    version_delta: dict[str, Any],
    ml_summary: dict[str, Any] | None,
    first_evidence_id: Callable[[list[dict[str, Any]], str], int | None],
    is_structured_metric: Callable[[dict[str, Any]], bool],
    contains_demo_placeholder: Callable[[str | None], bool],
    authority_sources: Callable[[str, str], list[dict[str, Any]]],
    synthetic_history_source: str,
    log_tool_invocation: Callable[..., None],
) -> None:
    symbol = holding["symbol"]
    market_id = first_evidence_id(evidence, "market_data")
    financial_id = first_evidence_id(evidence, "financial_report")
    disclosure_id = first_evidence_id(evidence, "disclosure")
    news_id = first_evidence_id(evidence, "news_event")
    analogy_id = first_evidence_id(evidence, "historical_analogy")
    inference_id = first_evidence_id(evidence, "model_inference")
    fallback_evidence_id = next((int(item["id"]) for item in evidence if item.get("id") is not None), None)
    real_document = document_analysis.get("sourceType") != "demo_cache"
    structured_metrics = [item for item in document_analysis.get("metrics", []) if is_structured_metric(item)]
    ml_summary = ml_summary or {}
    ml_model_valid = ml_summary.get("modelStatus") == "valid" and bool(ml_summary.get("modelId"))
    ml_calibrated = ml_summary.get("calibrationStatus") == "valid" and bool(ml_summary.get("modelId"))
    ml_scenarios = int(ml_summary.get("similarScenarioCount") or 0)
    disclosure_evidence = next((item for item in evidence if item["sourceType"] == "disclosure"), None)
    disclosure_ok = bool(disclosure_evidence and "刷新成功" in disclosure_evidence.get("claim", "") and disclosure_evidence.get("confidence", 0) >= 0.7)
    historical_sources = sorted({item.get("dataSource", "unknown") for item in analogies}) or ["no history"]
    historical_has_synthetic = any(synthetic_history_source in source for source in historical_sources)
    placeholder_news = any(
        contains_demo_placeholder(item.get("claim")) or contains_demo_placeholder(item.get("sourceName"))
        or "刷新失败" in item.get("claim", "")
        or float(item.get("confidence", 0)) < 0.5
        for item in evidence
        if item["sourceType"] == "news_event"
    )
    expired_count = len(evidence_graph["expiredEvidenceIds"])
    logs = [
        ("market_snapshot", {"symbol": symbol, "market": holding["market"]}, f"{holding.get('dataSource', 'unknown')} 返回 dataStatus={holding.get('dataStatus', 'unknown')}，dayChange={holding.get('dayChange', 0)}。", holding.get("dataSource", "unknown"), "success" if holding.get("dataStatus") == "live" else "degraded", None if holding.get("dataStatus") == "live" else "实时接口不可用或未配置；使用成本价/缓存兜底并禁止当作最新市场事实。", market_id),
        ("historical_prices", {"symbol": symbol, "limit": 760}, f"生成 {len(analogies)} 个历史情景；来源: {', '.join(historical_sources)}。", ", ".join(historical_sources), "degraded" if historical_has_synthetic else "success", "历史价格包含 synthetic_demo_price_path，混合区间只能作为演示或需补真实历史数据。" if historical_has_synthetic else None, analogy_id),
        ("financial_report_parser", {"symbol": symbol, "documentId": document_analysis.get("documentId")}, f"文档 {document_analysis.get('filename')}，结构化指标 {len(structured_metrics)} 条；权威 filing evidence={financial_id}。", document_analysis.get("sourceType", "unknown") if real_document else (disclosure_evidence or {}).get("sourceName", "unknown"), "success" if real_document and disclosure_ok and structured_metrics else "degraded", "缺少上传文档的结构化表格数字，或权威 filing evidence 尚未核验。" if not (real_document and disclosure_ok and structured_metrics) else None, financial_id),
        ("announcement_search", {"symbol": symbol, "market": holding["market"]}, (disclosure_evidence or {}).get("claim", f"生成 {len(authority_sources(symbol, holding['market']))} 个权威公告/披露检索入口。"), (disclosure_evidence or {}).get("sourceName", "authority source registry"), "success" if disclosure_ok else "degraded", None if disclosure_ok else "权威披露 provider 未返回有效 filing，保留入口但报告需降级。", disclosure_id),
        ("news_search", {"symbol": symbol, "freshness": "24 hours"}, "新闻事件证据已进入 evidence list。" if not placeholder_news else "新闻事件仍为占位、失败或低置信度证据。", "public news source cache", "degraded" if placeholder_news else "success", "新闻源为 demo placeholder、拉取失败或缺少真实来源。" if placeholder_news else None, news_id),
        ("document_parser", {"symbol": symbol, "documentId": document_analysis.get("documentId")}, f"文本/表格/图表块: {document_analysis.get('blocks', [])}。", document_analysis.get("sourceType", "unknown"), "success" if real_document else "degraded", "未上传真实文档，当前只是解析管线样例。" if not real_document else None, financial_id),
        ("metric_calculator", {"symbol": symbol, "metrics": [item.get("metric_name") for item in document_analysis.get("metrics", [])]}, f"可计算结构化指标 {len(structured_metrics)} 条；组合市值和收益由代码计算。", "structured metric engine", "success" if real_document and structured_metrics else "degraded", "指标来自 demo table 或候选文本，不能作为事实计算输入。" if not (real_document and structured_metrics) else None, financial_id),
        ("time_series_feature_builder", {"symbol": symbol, "windows": [60, 120, 252], "asOfDate": ml_summary.get("asOfDate")}, f"时序特征 asOfDate={ml_summary.get('asOfDate', 'missing')}，modelStatus={ml_summary.get('modelStatus', 'missing')}。", "local ML feature store", "success" if ml_summary.get("asOfDate") else "degraded", "缺少有效 feature snapshot，模型推断必须降级。" if not ml_summary.get("asOfDate") else None, inference_id),
        ("cnn_signal_encoder", {"symbol": symbol, "modelId": ml_summary.get("modelId"), "modelType": ml_summary.get("modelType")}, f"模型 {ml_summary.get('modelId', 'missing')} 输出 riskRegime={ml_summary.get('riskRegime', 'missing')}。", "local ML model registry", "success" if ml_model_valid else "degraded", "缺少有效 CNN/时序模型推断，局部信号不得进入结论。" if not ml_model_valid else None, inference_id),
        ("transformer_scenario_encoder", {"symbol": symbol, "modelId": ml_summary.get("modelId"), "scenarioCount": ml_scenarios}, f"相似历史情景 {ml_scenarios} 个；只展示风险分布，不输出预测。", "local ML scenario index", "success" if ml_model_valid and ml_scenarios > 0 else "degraded", "缺少有效 embedding 相似情景或模型已过期，历史情景编码不得作为预测依据。" if not (ml_model_valid and ml_scenarios > 0) else None, inference_id),
        ("calibration_validator", {"symbol": symbol, "modelId": ml_summary.get("modelId"), "calibrationStatus": ml_summary.get("calibrationStatus")}, f"校准状态 {ml_summary.get('calibrationStatus', 'missing')}，validUntil={ml_summary.get('validUntil', 'missing')}。", "local ML audit registry", "success" if ml_calibrated else "degraded", "缺少有效校准或样本外验证记录，模型结论必须降级。" if not ml_calibrated else None, inference_id),
        ("authority_retrieval", {"symbol": symbol, "market": holding["market"]}, f"Judge 可检查 {len(audit['authoritySources'])} 个权威来源入口。", "authority source registry", "success", None, disclosure_id or inference_id),
        ("research_quality_judge", {"symbol": symbol, "claimCount": len(evidence_graph["claims"])}, f"质量分 {audit['score']}；结论: {audit['verdict']}。", "Research Quality Judge", "success", None, inference_id),
        ("report_revision_loop", {"symbol": symbol, "auditScore": audit["score"]}, revision_loop["revisedSummary"], "report revision loop", "success" if revision_loop["finalStatus"] == "approved_research_note" else "degraded", "; ".join(revision_loop["blockedBy"]) if revision_loop["blockedBy"] else None, inference_id),
        ("evidence_refresh", {"symbol": symbol, "expiredEvidenceIds": evidence_graph["expiredEvidenceIds"]}, f"过期证据 {expired_count} 条；版本变化: {version_delta['summary']}", "evidence refresh scheduler", "success" if expired_count == 0 else "degraded", "存在过期证据，依赖推断必须失效或重跑。" if expired_count else None, inference_id),
    ]
    for tool_id, input_payload, output_summary, source_name, status, failure_reason, evidence_id in logs:
        log_tool_invocation(
            run_id,
            tool_id,
            symbol,
            input_payload,
            output_summary,
            source_name,
            status,
            failure_reason=failure_reason,
            evidence_id=evidence_id or fallback_evidence_id,
        )


def build_agent_workflow(
    *,
    symbol: str,
    preference_label: str,
    uploaded_doc: bool,
    analogies: list[dict[str, Any]],
    audit_score: int,
    ml_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    ml_valid = ml_summary.get("modelStatus") == "valid"
    return [
        {"role": "行情与资讯收集 Agent", "kind": "Agent", "status": "live-first", "output": f"{symbol} 行情、新闻、公告入口和证据时间戳进入证据链。"},
        {"role": "财务数据分析 Skill", "kind": "Skill", "status": "uploaded_report" if uploaded_doc else "needs filing", "output": "财报表格候选指标已入结构化库。" if uploaded_doc else "等待真实财报/公告上传，demo_cache 不作为事实来源。"},
        {"role": "策略回测 Skill", "kind": "Skill", "status": "scenario-ready" if analogies else "insufficient history", "output": "历史情景按 asOfDate 截断，展示 1周/1月/3月收益与最大回撤，并提示样本外风险。"},
        {"role": "Time-Series Feature Builder Skill", "kind": "Skill", "status": "ready" if ml_summary.get("asOfDate") else "missing", "output": f"构建 {symbol} 60/120/252 日窗口特征，输出给本地模型；缺失时不让 LLM 读取原始长序列。"},
        {"role": "CNN Local Signal Skill", "kind": "Skill", "status": "valid" if ml_valid else "unavailable", "output": "识别成交量异常、价格加速和波动突变，作为低 token 局部信号。" if ml_valid else "模型缺失或过期，局部信号不进入研究结论。"},
        {"role": "Transformer Scenario Encoder Skill", "kind": "Skill", "status": "valid" if ml_summary.get("similarScenarioCount", 0) else "pending", "output": f"检索 {ml_summary.get('similarScenarioCount', 0)} 个 embedding 相似历史窗口，展示风险分布而非预测。"},
        {"role": "Calibration Validator Skill", "kind": "Skill", "status": ml_summary.get("calibrationStatus", "missing"), "output": f"检查 modelId={ml_summary.get('modelId', 'missing')} 的有效期、样本外指标和校准状态。"},
        {"role": "观察池管理 Agent", "kind": "Agent", "status": "active", "output": f"按{preference_label}维护观察项、证据有效期和经验历史池。"},
        {"role": "信号提醒 Agent", "kind": "Agent", "status": "armed", "output": "监听行情过期、财报窗口、负面新闻、回撤和集中度触发器。"},
        {"role": "研究报告生成 Agent", "kind": "Agent", "status": "drafted", "output": "生成文档解释、证据表格、图表、历史类比、反方观点和观察清单。"},
        {"role": "LLM Judge 审稿 Agent", "kind": "Agent", "status": "reviewed", "output": f"只审研究质量，不判断买卖价值；当前质量分 {audit_score}。"},
    ]


def build_research_text(*, name: str, sector: str, preference_label: str) -> dict[str, Any]:
    return {
        "riskLabel": "中高风险" if sector in {"AI 算力", "电动车"} else "中风险",
        "riskLevel": "high" if sector in {"AI 算力", "电动车"} else "medium",
        "documentBlocks": [
            {"title": "Agent 综合摘要", "text": f"{name} 当前分析采用{preference_label}。Investment Agent Workflow 将行情与资讯收集、财务分析、策略回测、观察池、信号提醒、报告生成和 Judge 审稿拆成独立 Agent/Skill。"},
            {"title": "反方观点 / 研究质量审查", "text": "当前研究最可能被三类证据推翻: 最新财报指引转弱、行业新闻热度降温、价格快速上涨后进入高波动回撤。Judge 审的是研究严谨性，不评价是否值得买。"},
            {"title": "观察建议", "text": "建议继续观察关键触发条件，不输出确定性买卖建议。若证据过期，系统应重新生成模型推断并将旧记录归档到经验历史池。"},
        ],
    }
