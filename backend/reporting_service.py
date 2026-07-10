from __future__ import annotations

from typing import Any, Callable


def report_snapshot_path(symbol: str, run_id: str) -> str:
    return f"/api/reports/{symbol}.md?run_id={run_id}"


def attach_report_snapshot(
    *,
    payload: dict[str, Any],
    preference: str,
    user_id: int | None,
    store_report_snapshot: Callable[[str, str, str, str, str], None],
    markdown_builder: Callable[..., str] | None = None,
) -> dict[str, Any]:
    builder = markdown_builder or build_markdown_report
    markdown = builder(
        symbol=payload["symbol"],
        preference=preference,
        user_id=user_id,
        research_payload=lambda *_: payload,
    )
    run = {
        **payload["run"],
        "reportPath": report_snapshot_path(payload["symbol"], payload["run"]["runId"]),
    }
    store_report_snapshot(
        run["runId"],
        payload["symbol"],
        preference,
        run.get("reportVersion", "report-latest"),
        markdown,
    )
    report_versions = {
        **payload["reportVersions"],
        "current": run,
        "recentRuns": [
            {**item, "reportPath": report_snapshot_path(payload["symbol"], item["runId"])}
            for item in payload["reportVersions"]["recentRuns"]
        ],
    }
    return {**payload, "run": run, "reportVersions": report_versions}


def build_markdown_report(
    *,
    symbol: str,
    preference: str,
    user_id: int | None,
    research_payload: Callable[[str, str, int | None], dict[str, Any]],
) -> str:
    payload = research_payload(symbol, preference, user_id)
    evidence_rows = "\n".join(
        f"| {item['sourceType']} | {item['claim']} | {item['sourceName']} | {item['observedAt']} | {item['validUntil']} | {round(item['confidence'] * 100)}% |"
        for item in payload["evidence"]
    )
    analogy_rows = "\n".join(
        f"| {item['asOfDate']} | {item['pattern']} | {round(item['similarity'] * 100)}% | {item['return1w']}% | {item['return1m']}% | {item['return3m']}% | {item['maxDrawdown']}% |"
        for item in payload["historicalAnalogies"]
    )
    blocks = "\n\n".join(f"### {block['title']}\n\n{block['text']}" for block in payload["documentBlocks"])
    workflow_rows = "\n".join(
        f"- **{item['role']}** ({item['kind']} · {item['status']}): {item['output']}" for item in payload["agentWorkflow"]
    )
    ml = payload.get("mlRiskSummary", {})
    distribution = ml.get("riskDistribution", {})
    var_breach = distribution.get("varBreach", {})
    feature_audit = ml.get("featureStoreAudit", {})
    validation = ml.get("validationMetrics", {})
    compression = payload.get("tokenCompressionReport", {})
    ml_summary = (
        f"- 模型状态: {ml.get('modelStatus', 'missing')}\n"
        f"- 模型版本: {ml.get('modelId', 'missing')}\n"
        f"- 校准状态: {ml.get('calibrationStatus', 'missing')}\n"
        f"- 1月风险 regime: {ml.get('riskRegime', 'missing')}\n"
        f"- 1周最大回撤 P90: {distribution.get('drawdownQuantiles1w', {}).get('p90', 'missing')}\n"
        f"- 1月最大回撤 P90: {ml.get('drawdownP90_1m', 'missing')}\n"
        f"- 1月最大回撤 P95: {ml.get('drawdownP95_1m', 'missing')}\n"
        f"- VaR breach probability: {var_breach.get('breachProbability', 'missing')} at threshold {var_breach.get('threshold', 'missing')}\n"
        f"- Point-in-Time Feature Store: {feature_audit.get('checkedFieldCount', 0)} fields, future leakage {feature_audit.get('futureLeakageCount', 'missing')}\n"
        f"- Calibration/Backtest: ECE={validation.get('calibration_ece', 'missing')}, pinball={validation.get('pinball_loss', 'missing')}, CRPS={validation.get('crps', 'missing')}, VaR breach rate={validation.get('var_breach_rate', 'missing')}\n"
        f"- 相似情景数量: {ml.get('similarScenarioCount', 0)}"
    )
    compression_summary = (
        f"- Raw token estimate: {compression.get('rawTokenEstimate', 'missing')}\n"
        f"- Structured token estimate: {compression.get('structuredTokenEstimate', 'missing')}\n"
        f"- Token reduction: {compression.get('tokenReductionPercent', 'missing')}%\n"
        f"- Conclusion consistency: {compression.get('conclusionConsistency', 'missing')}"
    )
    quality_rows = "\n".join(
        f"- **{item['label']}**: {'通过' if item['passed'] else '需补强'}。{item['detail']}" for item in payload["evidenceAudit"]["dimensions"]
    )
    audit_rows = "\n".join(
        f"- **{item['title']}** ({item['severity']}): {item['detail']}" for item in payload["evidenceAudit"]["findings"]
    )
    checklist_rows = "\n".join(
        f"- {item['item']}: {item['trigger']} ({item['frequency']}, {item['status']})" for item in payload["observationChecklist"]
    )
    generated_at = payload["run"]["finishedAt"] if payload.get("run") else "n/a"
    source_meta = payload.get("sourceMeta", {})
    quality_gate = payload.get("qualityGate", {})
    return f"""# {payload['symbol']} 投研报告

生成时间: {generated_at}
Run ID: {payload['run']['runId']}
Report Version: {payload['run'].get('reportVersion', 'n/a')}
偏好: {payload['profile']['label']}
风险等级: {payload['riskLabel']}
风险评分: {payload['run']['riskScore']}
研究质量评分: {payload['evidenceAudit']['score']}
质量门禁: {quality_gate.get('status', 'n/a')} {' / '.join(quality_gate.get('reasons', []))}
数据来源: mode={source_meta.get('mode', 'n/a')} provider={source_meta.get('provider', 'n/a')} as_of={source_meta.get('as_of', 'n/a')} synthetic_ratio={source_meta.get('synthetic_ratio', 'n/a')}

> 仅供研究学习，不构成投资建议。历史类比只展示风险分布，不作为涨跌预测。

## 一页摘要

{payload['run']['summary']}

{blocks}

## Agent / Skill 工作流

{workflow_rows}

## 时序模型风险分布

{ml_summary}

## Agent Token Compression Report

{compression_summary}

## 证据链

| 类型 | 结论/事实 | 来源 | 观察时间 | 有效期 | 置信度 |
| --- | --- | --- | --- | --- | --- |
{evidence_rows}

## Research Quality Judge 审稿

审稿边界: {payload['evidenceAudit']['scope']}
审稿结论: {payload['evidenceAudit']['verdict']}
研究质量评分: {payload['evidenceAudit']['score']}

{quality_rows}

{audit_rows}

## 历史相似情景

| 日期 | 模式 | 相似度 | 后续 1 周 | 后续 1 月 | 后续 3 月 | 最大回撤 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
{analogy_rows}

## Bull / Bear Debate

### 支持观点

{chr(10).join('- ' + item for item in payload['debate']['bull'])}

### 反方观点

{chr(10).join('- ' + item for item in payload['debate']['bear'])}

### 中立裁判

{payload['debate']['judge']['detail']}

## 观察清单

{checklist_rows}
"""
