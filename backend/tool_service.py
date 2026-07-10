from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any, Callable

from .schemas import ToolInvocationRecord
from .tool_repository import fetch_tool_invocation_rows, insert_tool_invocation, upsert_tool_registry


STANDARD_TOOLS = [
    {
        "toolId": "market_snapshot",
        "name": "实时行情快照",
        "category": "market_data",
        "description": "拉取 A 股/美股/基金最新价格、涨跌幅和观察时间；失败时必须标注兜底口径。",
        "freshnessRule": "1 trading day",
        "outputContract": "price, day_change, observed_at, source_name, evidence_id",
    },
    {
        "toolId": "historical_prices",
        "name": "历史价格序列",
        "category": "market_data",
        "description": "读取历史价格，生成组合曲线、回撤和历史类比输入。",
        "freshnessRule": "1 trading day",
        "outputContract": "price_series, source_name, scenario_count, evidence_id",
    },
    {
        "toolId": "financial_report_parser",
        "name": "财报/公告解析",
        "category": "financial_report",
        "description": "解析上传的 PDF/TXT/CSV，拆出文本块、表格块、图表摘要和脚注块。",
        "freshnessRule": "filing cycle",
        "outputContract": "document_id, block_counts, metric_count, evidence_id",
    },
    {
        "toolId": "announcement_search",
        "name": "公告权威检索",
        "category": "disclosure",
        "description": "生成交易所、监管机构和公司 IR 的权威检索入口。",
        "freshnessRule": "event driven",
        "outputContract": "authority_sources, source_count",
    },
    {
        "toolId": "news_search",
        "name": "新闻事件检索",
        "category": "news_event",
        "description": "读取新闻事件证据，要求 24 小时有效期和来源名称。",
        "freshnessRule": "24 hours",
        "outputContract": "event_summary, observed_at, valid_until, evidence_id",
    },
    {
        "toolId": "document_parser",
        "name": "多模态文档拆块",
        "category": "document",
        "description": "将文档拆成文本、表格、图表摘要；数字计算只读取结构化表格。",
        "freshnessRule": "filing cycle",
        "outputContract": "text_blocks, table_blocks, chart_blocks, footnotes, document_id",
    },
    {
        "toolId": "metric_calculator",
        "name": "结构化指标计算",
        "category": "calculation",
        "description": "从表格块计算财务指标、组合收益、今日盈亏和风险分布，禁止 LLM 心算。",
        "freshnessRule": "depends on inputs",
        "outputContract": "metric_count, derived_metrics, source_blocks",
    },
    {
        "toolId": "time_series_feature_builder",
        "name": "时序特征构建",
        "category": "ml_feature",
        "description": "按 asOfDate 截断行情窗口，生成 CNN/Transformer/表格模型共享的点时特征。",
        "freshnessRule": "1 trading day",
        "outputContract": "feature_snapshot_id, feature_version, as_of_date, source_status",
    },
    {
        "toolId": "cnn_signal_encoder",
        "name": "CNN 局部信号编码",
        "category": "ml_model",
        "description": "识别价格加速、成交量异常和短期波动结构，输出局部风险信号而非买卖建议。",
        "freshnessRule": "depends on feature snapshot",
        "outputContract": "local_signals, confidence, model_id, calibration_status",
    },
    {
        "toolId": "transformer_scenario_encoder",
        "name": "Transformer 历史情景编码",
        "category": "ml_model",
        "description": "将长窗口行情、事件和财报窗口编码为情景向量，用于相似历史阶段检索。",
        "freshnessRule": "depends on feature snapshot",
        "outputContract": "embedding_id, matched_scenarios, leakage_check",
    },
    {
        "toolId": "calibration_validator",
        "name": "校准与样本外验证",
        "category": "ml_audit",
        "description": "检查模型训练截止日、时间切分、校准状态和是否依赖过期证据。",
        "freshnessRule": "per model release and per inference",
        "outputContract": "calibration_status, trained_until, validation_metrics, audit_flags",
    },
    {
        "toolId": "authority_retrieval",
        "name": "权威来源检索",
        "category": "retrieval",
        "description": "列出监管、交易所、公司 IR 等权威来源，并给 Judge 做交叉检查。",
        "freshnessRule": "event driven",
        "outputContract": "source_name, url, authority, status",
    },
    {
        "toolId": "research_quality_judge",
        "name": "Research Quality Judge",
        "category": "judge",
        "description": "只审研究严谨性：证据过期、数字来源、事实/推断边界、bear case、荐股越界。",
        "freshnessRule": "per report run",
        "outputContract": "score, verdict, failed_dimensions",
    },
    {
        "toolId": "report_revision_loop",
        "name": "报告审计修订 Loop",
        "category": "loop",
        "description": "初稿、Judge 审稿、工具补证据、降级越界结论、生成修订稿。",
        "freshnessRule": "per report run",
        "outputContract": "draft_status, judge_verdict, actions, final_status",
    },
    {
        "toolId": "evidence_refresh",
        "name": "证据刷新与版本复盘",
        "category": "refresh",
        "description": "按证据有效期刷新并记录证据变化、结论变化和风险评分变化。",
        "freshnessRule": "scheduled or trigger based",
        "outputContract": "expired_count, risk_score_delta, version_summary",
    },
]


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def register_standard_tools(conn: sqlite3.Connection, *, updated_at: str) -> None:
    upsert_tool_registry(conn, tools=STANDARD_TOOLS, updated_at=updated_at)


def log_tool_invocation(
    *,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    run_id: str,
    tool_id: str,
    symbol: str,
    input_payload: dict[str, Any],
    output_summary: str,
    source_name: str,
    status: str,
    failure_reason: str | None = None,
    evidence_id: int | None = None,
) -> None:
    with closing(connect()) as conn:
        insert_tool_invocation(
            conn,
            run_id=run_id,
            tool_id=tool_id,
            symbol=symbol,
            input_json=json.dumps(input_payload, ensure_ascii=False, sort_keys=True),
            output_summary=output_summary,
            source_name=source_name,
            observed_at=iso(now_utc()),
            status=status,
            failure_reason=failure_reason,
            evidence_id=evidence_id,
        )
        conn.commit()


def get_tool_invocations(
    run_id: str,
    *,
    connect: Callable[[], sqlite3.Connection],
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_tool_invocation_rows(conn, run_id)
    records: list[dict[str, Any]] = []
    for row in rows:
        records.append(
            dump_model(
                ToolInvocationRecord(
                    id=row["id"],
                    runId=row["run_id"],
                    toolId=row["tool_id"],
                    name=row["name"],
                    category=row["category"],
                    description=row["description"],
                    freshnessRule=row["freshness_rule"],
                    outputContract=row["output_contract"],
                    symbol=row["symbol"],
                    input=json.loads(row["input_json"] or "{}"),
                    outputSummary=row["output_summary"],
                    sourceName=row["source_name"],
                    observedAt=row["observed_at"],
                    status=row["status"],
                    failureReason=row["failure_reason"],
                    evidenceId=row["evidence_id"],
                )
            )
        )
    return records
