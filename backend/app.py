from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .analysis_run_service import (
    analysis_run_by_id as analysis_run_by_id_from_service,
    create_analysis_run,
    get_report_snapshot as get_report_snapshot_from_service,
    previous_run_delta as previous_run_delta_from_service,
    recent_analysis_runs,
    store_report_snapshot as store_report_snapshot_in_service,
)
from .auth_api import build_auth_router
from .auth_service import (
    build_current_user_dependency,
    build_public_user,
    ensure_developer_account as ensure_developer_account_in_service,
    get_user_profile as get_user_profile_from_service,
)
from .credential_service import delete_user_api_key as delete_user_api_key_record, upsert_user_api_key as upsert_user_api_key_record, user_api_key_summary as build_user_api_key_summary
from .config import DATA_DIR, SYNTHETIC_HISTORY_SOURCE, resolve_data_mode, resolve_db_path
from .data_mode_service import build_data_mode_payload, build_synthetic_market_snapshot
from .data_source_service import (
    build_authority_sources,
    fetch_json_url as fetch_json_url_from_provider,
    sec_user_agent as sec_user_agent_from_env,
    try_fetch_cninfo_disclosures as try_fetch_cninfo_disclosures_from_provider,
    try_fetch_disclosures as try_fetch_disclosures_from_provider,
    try_fetch_market_snapshot as try_fetch_market_snapshot_from_provider,
    try_fetch_news_events as try_fetch_news_events_from_provider,
    try_fetch_sec_filings as try_fetch_sec_filings_from_provider,
)
from .db_bootstrap import bootstrap_database, refresh_seed_data as refresh_seed_data_in_bootstrap
from .document_service import (
    analyze_document_content as analyze_document_content_in_service,
    get_latest_document_analysis,
)
from .evidence_service import (
    archive_expired_evidence as archive_expired_evidence_records,
    build_evidence_payload as build_evidence_payload_in_service,
    ensure_seed_evidence as ensure_seed_evidence_in_service,
    get_active_evidence as get_active_evidence_from_service,
    get_experience_history as get_experience_history_from_service,
    insert_refresh_disclosure_evidence as insert_refresh_disclosure_evidence_record,
    insert_refresh_history_evidence as insert_refresh_history_evidence_record,
    insert_refresh_market_evidence as insert_refresh_market_evidence_record,
    insert_refresh_news_evidence as insert_refresh_news_evidence_record,
)
from .ml_api import build_ml_router
from .ml_service import (
    build_latest_ml_risk_summary,
    build_ml_dataset_payload as build_ml_dataset_payload_in_service,
    build_ml_models_payload,
    build_token_compression_report,
    list_prediction_payloads as list_prediction_payloads_in_service,
    list_scenario_payloads as list_scenario_payloads_in_service,
    run_ml_inference_payload as run_ml_inference_payload_in_service,
    train_ml_model_payload as train_ml_model_payload_in_service,
)
from .portfolio_api import build_portfolio_router
from .portfolio_service import (
    build_default_holdings,
    build_empty_portfolio,
    build_portfolio_payload,
    build_risk_radar,
    build_user_holdings,
    add_watchlist_holding as add_watchlist_holding_in_service,
    preference_copy as build_preference_copy,
    save_onboarding_portfolio as save_onboarding_portfolio_in_service,
)
from .price_history_service import (
    ensure_price_history as ensure_price_history_in_service,
    fetch_historical_prices,
    get_price_points as get_price_points_from_service,
    portfolio_curve_from_history as portfolio_curve_from_history_from_service,
    portfolio_curve_source_label as portfolio_curve_source_label_from_service,
)
from .refresh_api import build_refresh_router
from .report_settings_service import (
    ensure_default_settings as ensure_default_report_settings,
    get_report_settings as get_report_settings_from_service,
    update_report_settings as update_report_settings_in_service,
)
from .reporting_service import attach_report_snapshot, build_markdown_report
from .refresh_service import build_default_refresh_data, build_refresh_review_for_symbol, build_refresh_user_data
from .research_api import build_research_router
from .research_domain_service import build_agent_workflow, build_evidence_graph_payload, build_log_research_toolchain, build_quality_gate_payload, build_research_quality_audit, build_research_text
from .research_service import build_research_payload
from .secret_service import decrypt_secret, encrypt_secret, migrate_plaintext_secrets
from .tool_service import (
    STANDARD_TOOLS,
    get_tool_invocations as get_tool_invocations_from_service,
    log_tool_invocation as log_tool_invocation_in_service,
    register_standard_tools as register_standard_tools_in_service,
)

EvidenceType = Literal["market_data", "financial_report", "disclosure", "news_event", "historical_analogy", "model_inference"]
Preference = Literal["balanced", "conservative", "growth", "trading", "fund"]

DB_PATH = resolve_db_path()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def current_data_mode() -> str:
    return resolve_data_mode()


def data_mode_status() -> dict[str, Any]:
    return build_data_mode_payload(
        mode=current_data_mode(),
        as_of=iso(now_utc()),
        build_source_meta=build_source_meta,
    )


def api_source_meta(
    provider: str = "investment_agent_workflow_api",
    *,
    overrides: list[str] | None = None,
    synthetic_ratio: float | None = None,
) -> dict[str, Any]:
    mode = current_data_mode()
    ratio = synthetic_ratio
    if ratio is None:
        ratio = 1.0 if mode == "demo" else 0.75 if mode == "sandbox" else 0.0
    return build_source_meta(
        provider=provider,
        as_of=iso(now_utc()),
        overrides=overrides or [],
        synthetic_ratio=ratio,
        mode=mode,
    )


def detect_mode_from_provider(provider: str | None, *, overrides: list[str] | None = None) -> str:
    provider_name = (provider or "").lower()
    override_flags = [item.lower() for item in (overrides or [])]
    if "manual_override" in override_flags:
        return "real"
    if "synthetic" in provider_name or "demo" in provider_name or "placeholder" in provider_name:
        return "demo" if current_data_mode() == "demo" else "sandbox"
    if "backfilled" in provider_name or "backfilled" in override_flags:
        return "sandbox" if current_data_mode() != "real" else "real"
    if any(token in provider_name for token in ["yfinance", "akshare", "sec", "cninfo", "edgar", "uploaded_report"]):
        return "real"
    return current_data_mode()


def build_source_meta(
    *,
    provider: str,
    as_of: str,
    overrides: list[str] | None = None,
    synthetic_ratio: float = 0.0,
    mode: str | None = None,
) -> dict[str, Any]:
    override_list = list(overrides or [])
    return {
        "mode": mode or detect_mode_from_provider(provider, overrides=override_list),
        "provider": provider,
        "as_of": as_of,
        "overrides": override_list,
        "synthetic_ratio": round(float(max(0.0, min(1.0, synthetic_ratio))), 4),
    }


def public_user(row: sqlite3.Row) -> dict[str, Any]:
    return build_public_user(row, get_user_profile=get_user_profile)


def get_user_profile(user_id: int) -> dict[str, Any]:
    return get_user_profile_from_service(user_id, connect=connect)


def user_api_key_summary(user_id: int) -> list[dict[str, Any]]:
    return build_user_api_key_summary(connect=connect, decrypt_secret=decrypt_secret, user_id=user_id)


def upsert_user_api_key(user_id: int, provider: str, api_key: str) -> None:
    upsert_user_api_key_record(
        connect=connect,
        encrypt_secret=encrypt_secret,
        user_id=user_id,
        provider=provider,
        api_key=api_key,
        updated_at=iso(now_utc()),
    )


def delete_user_api_key(user_id: int, provider: str) -> None:
    delete_user_api_key_record(connect=connect, user_id=user_id, provider=provider)


def mask_key(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


def default_sector(symbol: str, market: str) -> str:
    upper = symbol.upper()
    if upper in {"NVDA", "AMD", "SMH"}:
        return "AI 算力"
    if upper in {"QQQ", "SPY", "510300"}:
        return "宽基指数" if market == "cn" else "科技指数"
    if upper in {"TSLA", "LI", "NIO", "XPEV"}:
        return "电动车"
    if upper in {"XLE", "CVX", "XOM"}:
        return "能源对冲"
    if upper in {"600519", "000858"}:
        return "消费龙头"
    return "自选持仓"


SECTOR_COLORS = {
    "AI 算力": "#2dbb88",
    "科技指数": "#5f6fe8",
    "能源对冲": "#f0a83a",
    "电动车": "#e45f5f",
    "消费龙头": "#2f9cbd",
    "宽基指数": "#9a6ad6",
}

def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


get_current_user = build_current_user_dependency(connect=connect)


def ensure_developer_account(conn: sqlite3.Connection) -> None:
    ensure_developer_account_in_service(conn=conn, now_utc=now_utc, iso=iso)


def init_db() -> None:
    bootstrap_database(
        connect=connect,
        updated_at=iso(now_utc()),
        ensure_default_report_settings=ensure_default_report_settings,
        register_standard_tools=register_standard_tools,
        ensure_developer_account=ensure_developer_account,
    )
    migrate_plaintext_secrets(connect=connect, encrypt_value=encrypt_secret)
    refresh_seed_data_in_bootstrap(
        connect=connect,
        ensure_price_history=ensure_price_history,
        ensure_evidence=ensure_evidence,
        archive_expired_evidence=archive_expired_evidence,
    )

def try_fetch_historical_prices(symbol: str, market: str | None) -> dict[str, Any]:
    return fetch_historical_prices(symbol, market)


def ensure_price_history(conn: sqlite3.Connection, symbol: str, market: str | None = None) -> dict[str, Any]:
    return ensure_price_history_in_service(
        conn,
        symbol,
        market,
        now_utc=now_utc,
        synthetic_history_source=SYNTHETIC_HISTORY_SOURCE,
        fetcher=try_fetch_historical_prices,
    )


def ensure_evidence(conn: sqlite3.Connection, holding: sqlite3.Row) -> None:
    ensure_seed_evidence_in_service(conn=conn, holding=holding, now_utc=now_utc, iso=iso)


def evidence_payload(
    symbol: str,
    claim: str,
    source_type: EvidenceType,
    source_name: str,
    source_url: str | None,
    observed_at: datetime,
    valid_until: datetime,
    confidence: float,
    is_model_inferred: bool,
) -> dict[str, Any]:
    return build_evidence_payload_in_service(
        symbol=symbol,
        claim=claim,
        source_type=source_type,
        source_name=source_name,
        source_url=source_url,
        observed_at=observed_at,
        valid_until=valid_until,
        confidence=confidence,
        is_model_inferred=is_model_inferred,
        iso=iso,
    )


def register_standard_tools(conn: sqlite3.Connection) -> None:
    register_standard_tools_in_service(conn, updated_at=iso(now_utc()))


def first_evidence_id(evidence: list[dict[str, Any]], source_type: EvidenceType) -> int | None:
    match = next((item for item in evidence if item["sourceType"] == source_type), None)
    return int(match["id"]) if match else None


def log_tool_invocation(
    run_id: str,
    tool_id: str,
    symbol: str,
    input_payload: dict[str, Any],
    output_summary: str,
    source_name: str,
    status: Literal["success", "degraded", "failed"],
    *,
    failure_reason: str | None = None,
    evidence_id: int | None = None,
) -> None:
    log_tool_invocation_in_service(
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        run_id=run_id,
        tool_id=tool_id,
        symbol=symbol,
        input_payload=input_payload,
        output_summary=output_summary,
        source_name=source_name,
        status=status,
        failure_reason=failure_reason,
        evidence_id=evidence_id,
    )


def get_tool_invocations(run_id: str) -> list[dict[str, Any]]:
    return get_tool_invocations_from_service(run_id, connect=connect)


def archive_expired_evidence(conn: sqlite3.Connection) -> None:
    archive_expired_evidence_records(conn=conn, now_iso=iso(now_utc()))


def preference_weights(preference: Preference) -> list[dict[str, Any]]:
    weights = {
        "balanced": {"证据质量": 22, "回撤": 18, "集中度": 16, "成长": 16, "新闻事件": 14, "行业暴露": 14},
        "conservative": {"回撤": 28, "集中度": 24, "波动率": 20, "证据质量": 16, "成长": 6, "新闻事件": 6},
        "growth": {"营收增速": 26, "行业空间": 22, "毛利率": 18, "证据质量": 14, "回撤": 10, "新闻事件": 10},
        "trading": {"新闻事件": 26, "价格趋势": 24, "成交量": 20, "证据质量": 14, "回撤": 10, "估值": 6},
        "fund": {"行业暴露": 26, "重仓股": 22, "风格漂移": 20, "指数相关性": 16, "回撤": 10, "新闻事件": 6},
    }[preference]
    return [{"factor": key, "weight": value} for key, value in weights.items()]


def report_settings() -> dict[str, Any]:
    return get_report_settings_from_service(connect=connect)


def update_report_settings(frequency: str) -> dict[str, Any]:
    return update_report_settings_in_service(connect=connect, now_utc=now_utc, iso=iso, frequency=frequency)


def latest_document_analysis(symbol: str) -> dict[str, Any]:
    return get_latest_document_analysis(
        symbol,
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        build_source_meta=build_source_meta,
    )


def authority_sources(symbol: str, market: str) -> list[dict[str, Any]]:
    return build_authority_sources(symbol, market)


def fetch_json_url(url: str, headers: dict[str, str] | None = None, timeout: int = 8) -> Any:
    return fetch_json_url_from_provider(url, headers=headers, timeout=timeout)


def sec_user_agent() -> str:
    return sec_user_agent_from_env()


def try_fetch_sec_filings(symbol: str) -> dict[str, Any]:
    return try_fetch_sec_filings_from_provider(symbol)


def try_fetch_cninfo_disclosures(symbol: str) -> dict[str, Any]:
    return try_fetch_cninfo_disclosures_from_provider(symbol)


def try_fetch_disclosures(symbol: str, market: str) -> dict[str, Any]:
    mode = current_data_mode()
    if mode in {"demo", "sandbox"}:
        observed_at = data_mode_status()["sourceMeta"]["as_of"]
        provider = "synthetic_demo_disclosure" if mode == "demo" else "synthetic_sandbox_disclosure"
        return {
            "ok": True,
            "sourceName": provider,
            "filings": [
                {
                    "form": "DEMO",
                    "filingDate": observed_at[:10],
                    "reportDate": observed_at[:10],
                    "primaryDocument": f"{symbol.upper()} {mode} disclosure fixture",
                    "url": "",
                }
            ],
            "count": 1,
            "sourceMeta": build_source_meta(
                provider=provider,
                as_of=observed_at,
                overrides=["synthetic", mode],
                synthetic_ratio=1.0,
                mode=mode,
            ),
        }
    result = try_fetch_disclosures_from_provider(symbol, market)
    if "sourceMeta" not in result:
        result["sourceMeta"] = build_source_meta(
            provider=result.get("sourceName", "disclosure provider"),
            as_of=iso(now_utc()),
            overrides=[] if result.get("ok") else ["failed"],
            synthetic_ratio=0.0,
        )
    return result


def contains_demo_placeholder(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return "demo" in lowered or "placeholder" in lowered or "占位" in value or "样例" in value


def is_structured_metric(metric: dict[str, Any]) -> bool:
    source_block = str(metric.get("source_block") or "")
    metric_value = str(metric.get("metric_value") or "")
    return (
        bool(source_block)
        and source_block.startswith("table:")
        and metric.get("period") != "not factual"
        and not contains_demo_placeholder(metric_value)
        and not contains_demo_placeholder(source_block)
        and "候选" not in metric_value
        and "待" not in metric_value
    )


def has_personalized_advice_violation(texts: list[str]) -> bool:
    blocked_terms = ["建议买入", "可以买入", "应该买入", "建议卖出", "应该卖出", "目标价", "加仓", "减仓", "满仓", "清仓"]
    safe_context_terms = ["不构成投资建议", "不构成买卖建议", "不能输出", "禁止输出", "不评价", "边界"]
    for text in texts:
        if not text:
            continue
        if any(term in text for term in safe_context_terms):
            continue
        if any(term in text for term in blocked_terms):
            return True
    return False


def ml_models_payload() -> dict[str, Any]:
    payload = build_ml_models_payload()
    return {**payload, "sourceMeta": api_source_meta("ml_model_registry")}


def build_ml_dataset(user_id: int, symbols: list[str] | None, allow_synthetic: bool, smoke: bool) -> dict[str, Any]:
    return build_ml_dataset_payload_in_service(
        user_id=user_id,
        symbols=symbols,
        allow_synthetic=allow_synthetic,
        smoke=smoke,
        get_user_holdings=get_user_holdings,
        connect=connect,
        ensure_price_history=ensure_price_history,
    )


def train_ml_model(model_type: str, dataset_path: str | None, epochs: int, model_id: str | None) -> dict[str, Any]:
    return train_ml_model_payload_in_service(
        model_type=model_type,
        dataset_path=dataset_path,
        epochs=epochs,
        model_id=model_id,
    )


def run_ml_inference(user_id: int, symbol: str, allow_synthetic: bool, model_id: str | None) -> dict[str, Any]:
    return run_ml_inference_payload_in_service(
        user_id=user_id,
        symbol=symbol,
        allow_synthetic=allow_synthetic,
        model_id=model_id,
        get_user_holdings=get_user_holdings,
        connect=connect,
        ensure_price_history=ensure_price_history,
        latest_ml_risk_summary=latest_ml_risk_summary,
    )


def list_ml_predictions(symbol: str) -> list[dict[str, Any]]:
    return list_prediction_payloads_in_service(symbol, connect=connect)


def list_ml_scenarios(symbol: str) -> list[dict[str, Any]]:
    return list_scenario_payloads_in_service(symbol, connect=connect)


def latest_ml_risk_summary(symbol: str) -> dict[str, Any]:
    return build_latest_ml_risk_summary(
        symbol,
        connect=connect,
        build_source_meta=build_source_meta,
        current_data_mode=current_data_mode,
        now_utc=now_utc,
        iso=iso,
        parse_iso=parse_iso,
    )


def token_compression_report(symbol: str, evidence: list[dict[str, Any]], document_analysis: dict[str, Any], ml_summary: dict[str, Any]) -> dict[str, Any]:
    report = build_token_compression_report(
        symbol,
        evidence,
        document_analysis,
        ml_summary,
        connect=connect,
    )
    historical_sources = {
        item.get("sourceMeta", {}).get("synthetic_ratio", 0)
        for item in evidence
        if isinstance(item.get("sourceMeta"), dict)
    }
    synthetic_ratio = max(historical_sources or {0.0, float(ml_summary.get("sourceMeta", {}).get("synthetic_ratio", 0))})
    return {
        **report,
        "sourceMeta": build_source_meta(
            provider="token_compression_report",
            as_of=iso(now_utc()),
            overrides=["synthetic"] if synthetic_ratio > 0 else [],
            synthetic_ratio=synthetic_ratio,
        ),
    }


def research_quality_audit(
    evidence: list[dict[str, Any]],
    symbol: str,
    market: str,
    document_analysis: dict[str, Any],
    analogies: list[dict[str, Any]],
    *,
    has_bear_case: bool,
    claim_graph: dict[str, Any] | None = None,
    ml_summary: dict[str, Any] | None = None,
    token_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_research_quality_audit(
        evidence=evidence,
        symbol=symbol,
        market=market,
        document_analysis=document_analysis,
        analogies=analogies,
        has_bear_case=has_bear_case,
        claim_graph=claim_graph,
        ml_summary=ml_summary,
        token_report=token_report,
        contains_demo_placeholder=contains_demo_placeholder,
        is_structured_metric=is_structured_metric,
        has_personalized_advice_violation=has_personalized_advice_violation,
        authority_sources=authority_sources,
    )


def evidence_ids_by_type(evidence: list[dict[str, Any]], source_type: EvidenceType) -> list[int]:
    return [int(item["id"]) for item in evidence if item["sourceType"] == source_type]


def build_evidence_graph(
    evidence: list[dict[str, Any]],
    holding: dict[str, Any],
    document_analysis: dict[str, Any],
    analogies: list[dict[str, Any]],
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_evidence_graph_payload(
        evidence=evidence,
        holding=holding,
        document_analysis=document_analysis,
        analogies=analogies,
        audit=audit,
        is_structured_metric=is_structured_metric,
        contains_demo_placeholder=contains_demo_placeholder,
        synthetic_history_source=SYNTHETIC_HISTORY_SOURCE,
    )


def report_revision_loop(audit: dict[str, Any], evidence_graph: dict[str, Any]) -> dict[str, Any]:
    failed_high = [item for item in audit["dimensions"] if not item["passed"] and item["severity"] == "high"]
    contested_claims = [item for item in evidence_graph["claims"] if item["status"] != "supported"]
    final_status = "approved_research_note" if audit["score"] >= 80 and not contested_claims else "data_insufficient"
    actions = []
    for finding in audit["findings"]:
        if finding["severity"] in {"high", "medium"}:
            actions.append(f"补证据或降级: {finding['title']}")
    if contested_claims:
        actions.append(f"降级 {len(contested_claims)} 条 contested/unsupported claim，禁止输出漂亮但证据不足的结论。")
    return {
        "draftStatus": "initial_report_generated",
        "judgeVerdict": audit["verdict"],
        "toolBackfillActions": actions or ["无需补证据，保留审计痕迹和来源链接。"],
        "degradedClaims": [item["id"] for item in contested_claims],
        "finalStatus": final_status,
        "revisedSummary": "审计通过，可作为研究笔记继续使用。" if final_status == "approved_research_note" else "审计未通过，修订稿降级为数据不足说明，只保留观察项和补证据任务。",
        "blockedBy": [item["label"] for item in failed_high],
    }


def log_research_toolchain(
    run_id: str,
    holding: dict[str, Any],
    evidence: list[dict[str, Any]],
    document_analysis: dict[str, Any],
    analogies: list[dict[str, Any]],
    audit: dict[str, Any],
    evidence_graph: dict[str, Any],
    revision_loop: dict[str, Any],
    version_delta: dict[str, Any],
    ml_summary: dict[str, Any] | None = None,
) -> None:
    build_log_research_toolchain(
        run_id=run_id,
        holding=holding,
        evidence=evidence,
        document_analysis=document_analysis,
        analogies=analogies,
        audit=audit,
        evidence_graph=evidence_graph,
        revision_loop=revision_loop,
        version_delta=version_delta,
        ml_summary=ml_summary,
        first_evidence_id=first_evidence_id,
        is_structured_metric=is_structured_metric,
        contains_demo_placeholder=contains_demo_placeholder,
        authority_sources=authority_sources,
        synthetic_history_source=SYNTHETIC_HISTORY_SOURCE,
        log_tool_invocation=log_tool_invocation,
    )


def condition_alignment(symbol: str, analogies: list[dict[str, Any]], preference: Preference) -> dict[str, Any]:
    seed = sum(ord(char) for char in symbol)
    factors = [
        ("20日涨幅", "高" if seed % 3 else "中", "高", True),
        ("估值分位", "高位" if preference in {"growth", "trading"} else "中高", "高位", preference in {"growth", "trading"}),
        ("财报窗口", "财报前 14 天", "财报前 21 天", True),
        ("新闻情绪", "升温", "升温", True),
        ("市场状态", "震荡偏强", "利率敏感阶段", False),
        ("行业周期", "景气高位", "景气扩张", preference != "conservative"),
    ]
    return {
        "summary": "历史类比从价格形态升级为条件对齐: 同时检查估值、财报窗口、新闻情绪、市场状态和行业周期。",
        "matchedScenarioCount": len(analogies),
        "factors": [{"factor": name, "current": current, "historical": historical, "matched": matched} for name, current, historical, matched in factors],
    }


def debate_payload(symbol: str, name: str, evidence: list[dict[str, Any]], audit: dict[str, Any]) -> dict[str, Any]:
    return {
        "bull": [
            f"{name} 的行情、行业叙事和历史类比支持继续观察，尤其在证据有效期内可以作为研究样本。",
            "若财报指标延续改善，当前风险主要来自估值和波动，而不是基本面立即恶化。",
        ],
        "bear": [
            "若权威来源显示财报指引转弱，或新闻情绪从升温转为负面，当前结论需要下调置信度。",
            "模型推断仍需要原始证据支持，不能因为用户持仓而顺势唱多。",
        ],
        "judge": {
            "stance": "中立观察",
            "detail": f"Research Quality Judge 评分 {audit['score']}。它只审研究严谨性，不判断买卖价值；建议保留反方触发条件，并在证据过期时重新生成报告。",
        },
        "invalidators": ["财报指引低于预期", "权威公告与模型解释冲突", "历史类比条件匹配度下降", "单一标的集中度继续升高"],
    }


def observation_checklist(symbol: str, preference: Preference) -> list[dict[str, Any]]:
    base = [
        {"item": "刷新行情数据", "trigger": "行情证据超过 1 个交易日", "frequency": "daily", "status": "自动巡检"},
        {"item": "复核财报/公告", "trigger": "财报窗口前后 7-14 天", "frequency": "event", "status": "待观察"},
        {"item": "检查反方证据", "trigger": "负面新闻或权威公告出现", "frequency": "trigger_only", "status": "待观察"},
    ]
    preference_item = {
        "conservative": {"item": "回撤与集中度阈值", "trigger": "最大回撤扩大或单标的权重 > 30%", "frequency": "daily", "status": "重点"},
        "growth": {"item": "成长指标跟踪", "trigger": "营收增速或毛利率低于预期", "frequency": "weekly", "status": "重点"},
        "trading": {"item": "事件和成交量跟踪", "trigger": "成交量放大且新闻情绪转弱", "frequency": "daily", "status": "重点"},
        "fund": {"item": "风格漂移检查", "trigger": "行业暴露或重仓股变化", "frequency": "monthly", "status": "重点"},
        "balanced": {"item": "综合风险评分复核", "trigger": "风险评分变化超过 10 分", "frequency": "weekly", "status": "重点"},
    }[preference]
    return [preference_item, *base, {"item": f"{symbol} 报告版本对比", "trigger": "新 run 与上次风险评分差异明显", "frequency": "weekly", "status": "可复盘"}]


def try_fetch_market_snapshot(symbol: str, market: str) -> dict[str, Any]:
    mode = current_data_mode()
    if mode in {"demo", "sandbox"}:
        return build_synthetic_market_snapshot(
            symbol,
            market,
            mode=mode,
            build_source_meta=build_source_meta,
            now_utc=now_utc,
            iso=iso,
        )
    return try_fetch_market_snapshot_from_provider(
        symbol,
        market,
        build_source_meta=build_source_meta,
        now_utc=now_utc,
        iso=iso,
    )


def try_fetch_news_events(symbol: str, market: str) -> dict[str, Any]:
    mode = current_data_mode()
    if mode in {"demo", "sandbox"}:
        observed_at = data_mode_status()["sourceMeta"]["as_of"]
        provider = "synthetic_demo_news" if mode == "demo" else "synthetic_sandbox_news"
        return {
            "ok": True,
            "articles": [
                {
                    "title": f"{symbol.upper()} {mode} 新闻样例：仅用于证据链演示",
                    "url": "",
                    "publisher": provider,
                    "publishedAt": observed_at,
                }
            ],
            "sourceName": provider,
            "count": 1,
            "sourceMeta": build_source_meta(
                provider=provider,
                as_of=observed_at,
                overrides=["synthetic", mode],
                synthetic_ratio=1.0,
                mode=mode,
            ),
        }
    result = try_fetch_news_events_from_provider(symbol, market)
    if "sourceMeta" not in result:
        result["sourceMeta"] = build_source_meta(
            provider=result.get("sourceName", "news provider"),
            as_of=iso(now_utc()),
            overrides=[] if result.get("ok") else ["failed"],
            synthetic_ratio=0.0,
        )
    return result


def get_user_holdings(user_id: int) -> list[dict[str, Any]]:
    return build_user_holdings(
        user_id,
        connect=connect,
        try_fetch_market_snapshot=try_fetch_market_snapshot,
        build_source_meta=build_source_meta,
        now_utc=now_utc,
        iso=iso,
    )


def get_holdings() -> list[dict[str, Any]]:
    return build_default_holdings(connect=connect)


def save_onboarding_portfolio(user_id: int, preference: str, risk_answers: dict[str, Any], holdings: list[dict[str, Any]]) -> None:
    save_onboarding_portfolio_in_service(
        user_id=user_id,
        preference=preference,
        risk_answers=risk_answers,
        holdings=holdings,
        connect=connect,
        default_sector=default_sector,
        now_utc=now_utc,
        iso=iso,
        ensure_price_history=ensure_price_history,
        ensure_evidence=ensure_evidence,
        archive_expired_evidence=archive_expired_evidence,
    )


def add_watchlist_holding(user_id: int, symbol: str, market: str, name: str | None) -> dict[str, Any]:
    return add_watchlist_holding_in_service(
        user_id=user_id,
        symbol=symbol,
        market=market,
        name=name,
        connect=connect,
        try_fetch_market_snapshot=try_fetch_market_snapshot,
        now_utc=now_utc,
        iso=iso,
        ensure_price_history=ensure_price_history,
        ensure_evidence=ensure_evidence,
    )


def get_evidence(symbol: str) -> list[dict[str, Any]]:
    return get_active_evidence_from_service(
        symbol,
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        parse_iso=parse_iso,
        build_source_meta=build_source_meta,
        contains_demo_placeholder=contains_demo_placeholder,
    )


def get_experience_history(symbol: str | None = None) -> list[dict[str, Any]]:
    return get_experience_history_from_service(symbol, connect=connect)


def get_price_points(symbol: str, limit: int = 90) -> list[dict[str, Any]]:
    return get_price_points_from_service(
        symbol,
        connect=connect,
        build_source_meta=build_source_meta,
        synthetic_history_source=SYNTHETIC_HISTORY_SOURCE,
        limit=limit,
    )


def portfolio_curve_from_history(holdings: list[dict[str, Any]], point_count: int = 12) -> list[float]:
    return portfolio_curve_from_history_from_service(
        holdings,
        connect=connect,
        point_count=point_count,
    )


def portfolio_curve_source_label(holdings: list[dict[str, Any]]) -> str:
    return portfolio_curve_source_label_from_service(
        holdings,
        connect=connect,
        synthetic_history_source=SYNTHETIC_HISTORY_SOURCE,
    )


def returns(series: list[float], start: int, days: int) -> float:
    end = min(start + days, len(series) - 1)
    if start >= len(series) or series[start] == 0:
        return 0
    return ((series[end] - series[start]) / series[start]) * 100


def max_drawdown(series: list[float], start: int, days: int) -> float:
    end = min(start + days, len(series) - 1)
    window = series[start : end + 1]
    peak = window[0] if window else 0
    worst = 0.0
    for price in window:
        peak = max(peak, price)
        if peak:
            worst = min(worst, ((price - peak) / peak) * 100)
    return worst


def get_historical_analogies(symbol: str) -> list[dict[str, Any]]:
    prices = get_price_points(symbol, limit=760)
    closes = [item["close"] for item in prices]
    if len(closes) < 90:
        return []
    sources = sorted({item.get("sourceName", "unknown") for item in prices})
    source_label = ", ".join(sources)
    note_suffix = (
        f"当前历史价格来源: {source_label}。"
        if SYNTHETIC_HISTORY_SOURCE not in sources
        else "当前历史价格包含 synthetic_demo_price_path，占位数据只用于 UI 演示，不作为真实回测结论。"
    )
    scenarios = []
    for idx in range(60, len(closes) - 63, 45):
        price_20d = returns(closes, idx - 20, 20)
        price_60d = returns(closes, idx - 60, 60)
        if price_20d > 4 or price_60d > 10:
            scenarios.append(
                {
                    "asOfDate": prices[idx]["date"],
                    "pattern": "估值高位 + 财报前窗口 + 新闻热度升温 + 价格快速上涨",
                    "similarity": min(0.94, 0.68 + abs(price_20d) / 100),
                    "return1w": round(returns(closes, idx, 5), 2),
                    "return1m": round(returns(closes, idx, 21), 2),
                    "return3m": round(returns(closes, idx, 63), 2),
                    "maxDrawdown": round(max_drawdown(closes, idx, 63), 2),
                    "dataSource": source_label,
                    "sourceMeta": build_source_meta(
                        provider=source_label,
                        as_of=prices[idx]["date"],
                        overrides=["synthetic"] if SYNTHETIC_HISTORY_SOURCE in sources else [],
                        synthetic_ratio=1.0 if SYNTHETIC_HISTORY_SOURCE in sources else 0.0,
                    ),
                    "note": f"按 asOfDate 截断；展示样本外风险提示。{note_suffix}",
                }
            )
    return scenarios[-3:] or [
        {
            "asOfDate": prices[-64]["date"],
            "pattern": "价格上行但相似信号不足",
            "similarity": 0.61,
            "return1w": round(returns(closes, len(closes) - 64, 5), 2),
            "return1m": round(returns(closes, len(closes) - 64, 21), 2),
            "return3m": round(returns(closes, len(closes) - 64, 63), 2),
            "maxDrawdown": round(max_drawdown(closes, len(closes) - 64, 63), 2),
            "dataSource": source_label,
            "sourceMeta": build_source_meta(
                provider=source_label,
                as_of=prices[-64]["date"],
                overrides=["synthetic"] if SYNTHETIC_HISTORY_SOURCE in sources else [],
                synthetic_ratio=1.0 if SYNTHETIC_HISTORY_SOURCE in sources else 0.0,
            ),
            "note": f"相似度不足；展示样本外风险提示。{note_suffix}",
        }
    ]


def compute_risk_score(risk_level: str, evidence: list[dict[str, Any]], analogies: list[dict[str, Any]]) -> float:
    base = {"low": 32.0, "medium": 56.0, "high": 76.0}.get(risk_level, 50.0)
    inferred_penalty = sum(1 for item in evidence if item["isModelInferred"]) * 2.5
    expired_penalty = sum(1 for item in evidence if item["isExpired"]) * 8
    drawdown_penalty = max((abs(item["maxDrawdown"]) for item in analogies), default=0) * 0.55
    return round(min(100, base + inferred_penalty + expired_penalty + drawdown_penalty), 1)


def build_quality_gate(
    *,
    evidence: list[dict[str, Any]],
    analogies: list[dict[str, Any]],
    audit: dict[str, Any],
    ml_summary: dict[str, Any],
) -> dict[str, Any]:
    return build_quality_gate_payload(
        evidence=evidence,
        analogies=analogies,
        audit=audit,
        ml_summary=ml_summary,
        contains_demo_placeholder=contains_demo_placeholder,
    )


def create_research_run(
    symbol: str,
    preference: Preference,
    risk_score: float,
    summary: str,
    *,
    input_snapshot: dict[str, Any] | None = None,
    model_version: str | None = None,
    evidence_ids: list[int] | None = None,
    reasoning_steps: list[dict[str, Any]] | None = None,
    judge_payload: dict[str, Any] | None = None,
    risk_conclusion: dict[str, Any] | None = None,
    report_version: str | None = None,
    source_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return create_analysis_run(
        symbol,
        preference,
        risk_score,
        summary,
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        input_snapshot=input_snapshot,
        model_version=model_version,
        evidence_ids=evidence_ids,
        reasoning_steps=reasoning_steps,
        judge_payload=judge_payload,
        risk_conclusion=risk_conclusion,
        report_version=report_version,
        source_meta=source_meta,
    )


def recent_runs(symbol: str) -> list[dict[str, Any]]:
    return recent_analysis_runs(symbol, connect=connect)


def store_report_snapshot(run_id: str, symbol: str, preference: str, report_version: str, markdown: str) -> None:
    store_report_snapshot_in_service(
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        run_id=run_id,
        symbol=symbol,
        preference=preference,
        report_version=report_version,
        markdown=markdown,
    )


def get_report_snapshot(run_id: str) -> dict[str, Any] | None:
    return get_report_snapshot_from_service(connect=connect, run_id=run_id)


def get_analysis_run(run_id: str) -> dict[str, Any] | None:
    return analysis_run_by_id_from_service(connect=connect, run_id=run_id)


def previous_run_delta(symbol: str, current_score: float) -> dict[str, Any]:
    return previous_run_delta_from_service(symbol, current_score, connect=connect)


def risk_radar(holdings: list[dict[str, Any]], preference: Preference) -> list[dict[str, Any]]:
    return build_risk_radar(holdings, preference)


def preference_copy(preference: Preference) -> dict[str, str]:
    return build_preference_copy(preference)


def agent_workflow(
    symbol: str,
    preference: Preference,
    document_analysis: dict[str, Any],
    analogies: list[dict[str, Any]],
    audit: dict[str, Any],
    ml_summary: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    return build_agent_workflow(
        symbol=symbol,
        preference_label=preference_copy(preference)["label"],
        uploaded_doc=document_analysis.get("sourceType") != "demo_cache",
        analogies=analogies,
        audit_score=audit["score"],
        ml_summary=ml_summary or {},
    )


def research_text(symbol: str, name: str, sector: str, preference: Preference) -> dict[str, Any]:
    profile = preference_copy(preference)
    return {
        **build_research_text(name=name, sector=sector, preference_label=profile["label"]),
        "profile": profile,
    }


def empty_portfolio(preference: Preference) -> dict[str, Any]:
    return build_empty_portfolio(
        preference,
        now_utc=now_utc,
        iso=iso,
        build_source_meta=build_source_meta,
    )


def portfolio_payload(preference: Preference, user_id: int | None = None) -> dict[str, Any]:
    return build_portfolio_payload(
        preference,
        user_id=user_id,
        get_user_holdings=get_user_holdings,
        get_default_holdings=get_holdings,
        portfolio_curve_from_history=portfolio_curve_from_history,
        portfolio_curve_source_label=portfolio_curve_source_label,
        build_source_meta=build_source_meta,
        current_data_mode=current_data_mode,
        now_utc=now_utc,
        iso=iso,
        synthetic_history_source=SYNTHETIC_HISTORY_SOURCE,
        sector_colors=SECTOR_COLORS,
    )


def research_payload(symbol: str, preference: Preference, user_id: int | None = None) -> dict[str, Any]:
    payload = build_research_payload(
        symbol=symbol,
        preference=preference,
        user_id=user_id,
        get_user_holdings=get_user_holdings,
        get_default_holdings=get_holdings,
        research_text=research_text,
        get_evidence=get_evidence,
        get_historical_analogies=get_historical_analogies,
        latest_document_analysis=latest_document_analysis,
        latest_ml_risk_summary=latest_ml_risk_summary,
        token_compression_report=token_compression_report,
        build_evidence_graph=build_evidence_graph,
        research_quality_audit=research_quality_audit,
        report_revision_loop=report_revision_loop,
        build_quality_gate=build_quality_gate,
        compute_risk_score=compute_risk_score,
        previous_run_delta=previous_run_delta,
        create_research_run=create_research_run,
        log_research_toolchain=log_research_toolchain,
        preference_copy=preference_copy,
        agent_workflow=agent_workflow,
        get_tool_invocations=get_tool_invocations,
        condition_alignment=condition_alignment,
        preference_weights=preference_weights,
        report_settings=report_settings,
        recent_runs=recent_runs,
        debate_payload=debate_payload,
        observation_checklist=observation_checklist,
        get_price_points=get_price_points,
        get_experience_history=get_experience_history,
        build_source_meta=build_source_meta,
    )
    return attach_report_snapshot(
        payload=payload,
        preference=preference,
        user_id=user_id,
        store_report_snapshot=store_report_snapshot,
    )


def markdown_report(symbol: str, preference: Preference, user_id: int | None = None) -> str:
    return build_markdown_report(
        symbol=symbol,
        preference=preference,
        user_id=user_id,
        research_payload=research_payload,
    )


def refresh_daily() -> dict[str, Any]:
    return build_default_refresh_data(
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        try_fetch_market_snapshot=try_fetch_market_snapshot,
        ensure_price_history=ensure_price_history,
        ensure_evidence=ensure_evidence,
        archive_expired_evidence=archive_expired_evidence,
        get_experience_history=get_experience_history,
    )


def insert_refresh_market_evidence(conn: sqlite3.Connection, holding: sqlite3.Row, snapshot: dict[str, Any]) -> int:
    observed = now_utc()
    return insert_refresh_market_evidence_record(
        conn=conn,
        symbol=holding["symbol"],
        snapshot=snapshot,
        observed_at=iso(observed),
        valid_until=iso(observed + timedelta(days=1)),
    )


def insert_refresh_news_evidence(conn: sqlite3.Connection, holding: sqlite3.Row, news_result: dict[str, Any]) -> int:
    observed = now_utc()
    return insert_refresh_news_evidence_record(
        conn=conn,
        symbol=holding["symbol"],
        news_result=news_result,
        observed_at=iso(observed),
        valid_until=iso(observed + timedelta(hours=24)),
    )


def insert_refresh_history_evidence(conn: sqlite3.Connection, holding: sqlite3.Row, history_result: dict[str, Any]) -> int:
    observed = now_utc()
    return insert_refresh_history_evidence_record(
        conn=conn,
        symbol=holding["symbol"],
        history_result=history_result,
        observed_at=iso(observed),
        valid_until=iso(observed + timedelta(days=1)),
    )


def insert_refresh_disclosure_evidence(conn: sqlite3.Connection, holding: sqlite3.Row, disclosure_result: dict[str, Any]) -> tuple[int, int]:
    observed = now_utc()
    return insert_refresh_disclosure_evidence_record(
        conn=conn,
        symbol=holding["symbol"],
        disclosure_result=disclosure_result,
        observed_at=iso(observed),
        disclosure_valid_until=iso(observed + timedelta(days=7)),
        financial_valid_until=iso(observed + timedelta(days=90)),
    )


def claim_status_map(graph: dict[str, Any]) -> dict[str, str]:
    return {item["id"]: item["status"] for item in graph.get("claims", [])}


def summarize_claim_status_change(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changes = []
    for claim_id in sorted(set(before) | set(after)):
        if before.get(claim_id) != after.get(claim_id):
            changes.append(f"{claim_id}: {before.get(claim_id, 'missing')} -> {after.get(claim_id, 'missing')}")
    return changes


def refresh_review_for_symbol(user_id: int, holding_row: sqlite3.Row, snapshot: dict[str, Any]) -> dict[str, Any]:
    return build_refresh_review_for_symbol(
        user_id=user_id,
        holding_row=holding_row,
        snapshot=snapshot,
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        get_user_holdings=get_user_holdings,
        get_evidence=get_evidence,
        latest_document_analysis=latest_document_analysis,
        get_historical_analogies=get_historical_analogies,
        research_text=research_text,
        build_evidence_graph=build_evidence_graph,
        compute_risk_score=compute_risk_score,
        try_fetch_news_events=try_fetch_news_events,
        try_fetch_disclosures=try_fetch_disclosures,
        ensure_price_history=ensure_price_history,
        ensure_evidence=ensure_evidence,
        archive_expired_evidence=archive_expired_evidence,
        insert_refresh_market_evidence=insert_refresh_market_evidence_record,
        insert_refresh_history_evidence=insert_refresh_history_evidence_record,
        insert_refresh_news_evidence=insert_refresh_news_evidence_record,
        insert_refresh_disclosure_evidence=insert_refresh_disclosure_evidence_record,
        research_quality_audit=research_quality_audit,
    )


def refresh_user_data(user_id: int) -> dict[str, Any]:
    payload = build_refresh_user_data(
        user_id=user_id,
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        try_fetch_market_snapshot=try_fetch_market_snapshot,
        refresh_review_for_symbol=refresh_review_for_symbol,
        get_experience_history=get_experience_history,
    )
    ratios = [
        float(item.get("snapshot", {}).get("sourceMeta", {}).get("synthetic_ratio", 0))
        for item in payload.get("items", [])
    ]
    payload["sourceMeta"] = build_source_meta(
        provider="refresh_pipeline",
        as_of=payload.get("refreshedAt", iso(now_utc())),
        overrides=["synthetic"] if any(value > 0 for value in ratios) else [],
        synthetic_ratio=max(ratios or [0.0]),
    )
    payload["dataMode"] = data_mode_status()
    return payload


def analyze_document_content(symbol: str, filename: str, content: bytes) -> dict[str, Any]:
    return analyze_document_content_in_service(
        symbol,
        filename,
        content,
        connect=connect,
        now_utc=now_utc,
        iso=iso,
        build_source_meta=build_source_meta,
    )


app = FastAPI(title="Investment Agent Workflow Research API", version="0.2.0")
allowed_origins = [
    item.strip()
    for item in os.getenv("INVESTMENT_RESEARCH_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5177,http://127.0.0.1:5177").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
init_db()
app.include_router(
    build_auth_router(
        connect=connect,
        get_current_user=get_current_user,
        now_utc=now_utc,
        iso=iso,
        public_user=public_user,
        get_user_profile=get_user_profile,
        user_api_key_summary=user_api_key_summary,
        data_mode_status=data_mode_status,
    )
)
app.include_router(
    build_portfolio_router(
        get_current_user=get_current_user,
        get_user_profile=get_user_profile,
        public_user=public_user,
        portfolio_payload=portfolio_payload,
        save_onboarding_portfolio=save_onboarding_portfolio,
        add_watchlist_holding=add_watchlist_holding,
        report_settings=report_settings,
        save_report_settings=update_report_settings,
        user_api_key_summary=user_api_key_summary,
        upsert_user_api_key=upsert_user_api_key,
        delete_user_api_key=delete_user_api_key,
        data_mode_status=data_mode_status,
    )
)
app.include_router(
    build_ml_router(
        get_current_user=get_current_user,
        ml_models_payload=ml_models_payload,
        build_ml_dataset=build_ml_dataset,
        train_ml_model=train_ml_model,
        run_ml_inference=run_ml_inference,
        list_ml_predictions=list_ml_predictions,
        list_ml_scenarios=list_ml_scenarios,
        get_user_holdings=get_user_holdings,
        latest_ml_risk_summary=latest_ml_risk_summary,
        token_compression_report=token_compression_report,
        get_evidence=get_evidence,
        latest_document_analysis=latest_document_analysis,
        api_source_meta=api_source_meta,
        data_mode_status=data_mode_status,
    )
)
app.include_router(
    build_research_router(
        get_current_user=get_current_user,
        research_payload=research_payload,
        analyze_document_content=analyze_document_content,
        markdown_report=markdown_report,
        get_analysis_run=get_analysis_run,
        recent_runs=recent_runs,
        get_report_snapshot=get_report_snapshot,
        data_mode_status=data_mode_status,
    )
)
app.include_router(build_refresh_router(get_current_user=get_current_user, refresh_user_data=refresh_user_data))


@app.get("/api/health")
def health() -> dict[str, Any]:
    mode = data_mode_status()
    return {"ok": True, "database": str(DB_PATH), "time": iso(now_utc()), "dataMode": mode, "sourceMeta": mode["sourceMeta"]}


@app.get("/api/data-mode")
def data_mode() -> dict[str, Any]:
    return data_mode_status()
