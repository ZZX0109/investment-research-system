from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any

from .evidence_repository import (
    count_active_evidence,
    fetch_active_evidence_rows,
    fetch_active_evidence_ids_by_type,
    fetch_expired_evidence_rows,
    fetch_experience_history_rows,
    insert_evidence_record,
    insert_evidence_records,
    insert_experience_history,
    mark_evidence_archived,
    mark_evidence_superseded,
)
from .schemas import EvidenceRecord, ExperienceHistoryRecord


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def archive_expired_evidence(
    *,
    conn: sqlite3.Connection,
    now_iso: str,
) -> None:
    for row in fetch_expired_evidence_rows(conn, now_iso):
        insert_experience_history(
            conn,
            symbol=row["symbol"],
            archived_claim=row["claim"],
            source_type=row["source_type"],
            observed_at=row["observed_at"],
            archived_at=now_iso,
            reason="valid_until elapsed",
        )
        mark_evidence_archived(conn, evidence_id=row["id"], archived_at=now_iso)


def build_evidence_payload(
    *,
    symbol: str,
    claim: str,
    source_type: str,
    source_name: str,
    source_url: str | None,
    observed_at: datetime,
    valid_until: datetime,
    confidence: float,
    is_model_inferred: bool,
    iso: Any,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "claim": claim,
        "sourceType": source_type,
        "sourceName": source_name,
        "sourceUrl": source_url,
        "observedAt": iso(observed_at),
        "validUntil": iso(valid_until),
        "confidence": confidence,
        "isModelInferred": int(is_model_inferred),
    }


def _holding_value(holding: sqlite3.Row | dict[str, Any], key: str) -> Any:
    return holding[key]


def ensure_seed_evidence(
    *,
    conn: sqlite3.Connection,
    holding: sqlite3.Row | dict[str, Any],
    now_utc: Any,
    iso: Any,
) -> None:
    symbol = _holding_value(holding, "symbol")
    if count_active_evidence(conn, symbol) >= 5:
        return
    observed = now_utc()
    records = [
        build_evidence_payload(
            symbol=symbol,
            claim=f"{symbol} 行情证据槽位已创建；若实时接口失败，不能把缓存或成本价兜底当作最新市场事实。",
            source_type="market_data",
            source_name="yfinance/AkShare live-first; cache clearly labeled",
            source_url=None,
            observed_at=observed,
            valid_until=observed + timedelta(days=1),
            confidence=0.62,
            is_model_inferred=False,
            iso=iso,
        ),
        build_evidence_payload(
            symbol=symbol,
            claim=f"{_holding_value(holding, 'name')} 财务与估值摘要待真实财报/公告接入；当前模板证据仅用于展示字段结构。",
            source_type="financial_report",
            source_name="demo placeholder until SEC/EDGAR/AkShare filing is attached",
            source_url=None,
            observed_at=observed - timedelta(days=2),
            valid_until=observed + timedelta(days=5),
            confidence=0.38,
            is_model_inferred=False,
            iso=iso,
        ),
        build_evidence_payload(
            symbol=symbol,
            claim=f"{_holding_value(holding, 'sector')} 新闻事件待真实新闻源接入；当前模板不能作为事件事实。",
            source_type="news_event",
            source_name="demo placeholder; public news source required",
            source_url=None,
            observed_at=observed - timedelta(hours=8),
            valid_until=observed + timedelta(hours=16),
            confidence=0.32,
            is_model_inferred=False,
            iso=iso,
        ),
        build_evidence_payload(
            symbol=symbol,
            claim="历史类比模块当前可使用合成演示价格路径或真实历史路径；若来源为 synthetic_demo_price_path，只能用于 UI 演示。",
            source_type="historical_analogy",
            source_name="local historical scenario engine; source labeled per scenario",
            source_url=None,
            observed_at=observed,
            valid_until=observed + timedelta(days=1),
            confidence=0.42,
            is_model_inferred=False,
            iso=iso,
        ),
        build_evidence_payload(
            symbol=symbol,
            claim="综合建议必须基于有效真实证据；若依赖 demo placeholder，应降级为数据不足。",
            source_type="model_inference",
            source_name="Investment Agent Workflow Risk Review Agent",
            source_url=None,
            observed_at=observed,
            valid_until=observed + timedelta(days=1),
            confidence=0.35,
            is_model_inferred=True,
            iso=iso,
        ),
    ]
    insert_evidence_records(conn, records)


def get_active_evidence(
    symbol: str,
    *,
    connect: Any,
    now_utc: Any,
    iso: Any,
    parse_iso: Any,
    build_source_meta: Any,
    contains_demo_placeholder: Any,
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        archive_expired_evidence(conn=conn, now_iso=iso(now_utc()))
        conn.commit()
        rows = fetch_active_evidence_rows(conn, symbol)
    current = now_utc()
    records: list[dict[str, Any]] = []
    for row in rows:
        is_expired = parse_iso(row["valid_until"]) < current
        synthetic_ratio = 1.0 if contains_demo_placeholder(row["claim"]) or contains_demo_placeholder(row["source_name"]) else 0.0
        records.append(
            dump_model(
                EvidenceRecord(
                    id=row["id"],
                    claim=row["claim"],
                    sourceType=row["source_type"],
                    sourceName=row["source_name"],
                    sourceUrl=row["source_url"],
                    observedAt=row["observed_at"],
                    validUntil=row["valid_until"],
                    confidence=row["confidence"],
                    isModelInferred=bool(row["is_model_inferred"]),
                    isExpired=is_expired,
                    supersededBy=row["superseded_by"],
                    archivedAt=row["archived_at"],
                    sourceMeta=build_source_meta(
                        provider=row["source_name"],
                        as_of=row["observed_at"],
                        overrides=["expired"] if is_expired else [],
                        synthetic_ratio=synthetic_ratio,
                    ),
                )
            )
        )
    return records


def get_experience_history(
    symbol: str | None = None,
    *,
    connect: Any,
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_experience_history_rows(conn, symbol=symbol, limit=8 if symbol else 12)
    return [dump_model(ExperienceHistoryRecord(**dict(row))) for row in rows]


def insert_refresh_market_evidence(
    *,
    conn: sqlite3.Connection,
    symbol: str,
    snapshot: dict[str, Any],
    observed_at: str,
    valid_until: str,
) -> int:
    old_ids = fetch_active_evidence_ids_by_type(conn, symbol=symbol, source_type="market_data")
    if snapshot.get("ok"):
        claim = f"{symbol} 行情刷新成功: 最新价 {round(float(snapshot['marketValueHint']), 4)}，日内涨跌 {snapshot['dayChange']}%。"
        source_name = snapshot.get("sourceName", "market provider")
        confidence = 0.9
    else:
        claim = f"{symbol} 行情刷新失败: {snapshot.get('error', 'unknown error')}。当前不能把成本价或缓存当作最新市场事实。"
        source_name = snapshot.get("sourceName", "market provider")
        confidence = 0.42
    new_id = insert_evidence_record(
        conn,
        symbol=symbol,
        claim=claim,
        source_type="market_data",
        source_name=source_name,
        source_url=None,
        observed_at=observed_at,
        valid_until=valid_until,
        confidence=confidence,
        is_model_inferred=False,
    )
    mark_evidence_superseded(conn, evidence_ids=old_ids, superseded_by=new_id)
    return new_id


def insert_refresh_news_evidence(
    *,
    conn: sqlite3.Connection,
    symbol: str,
    news_result: dict[str, Any],
    observed_at: str,
    valid_until: str,
) -> int:
    old_ids = fetch_active_evidence_ids_by_type(conn, symbol=symbol, source_type="news_event")
    if news_result.get("ok"):
        titles = [item["title"] for item in news_result.get("articles", [])[:3]]
        claim = f"{symbol} 新闻刷新成功: " + "；".join(titles)
        confidence = 0.74
    else:
        claim = f"{symbol} 新闻刷新失败: {news_result.get('error', 'unknown error')}。新闻归因不能作为事实依据。"
        confidence = 0.3
    new_id = insert_evidence_record(
        conn,
        symbol=symbol,
        claim=claim,
        source_type="news_event",
        source_name=news_result.get("sourceName", "news provider"),
        source_url=(news_result.get("articles") or [{}])[0].get("url") if news_result.get("articles") else None,
        observed_at=observed_at,
        valid_until=valid_until,
        confidence=confidence,
        is_model_inferred=False,
    )
    mark_evidence_superseded(conn, evidence_ids=old_ids, superseded_by=new_id)
    return new_id


def insert_refresh_history_evidence(
    *,
    conn: sqlite3.Connection,
    symbol: str,
    history_result: dict[str, Any],
    observed_at: str,
    valid_until: str,
) -> int:
    old_ids = fetch_active_evidence_ids_by_type(conn, symbol=symbol, source_type="historical_analogy")
    if history_result.get("ok"):
        claim = f"{symbol} 历史价格刷新成功: {history_result.get('count', 0)} 条记录来自 {history_result.get('sourceName')}。历史类比可基于真实价格路径重算。"
        confidence = 0.78
    else:
        claim = f"{symbol} 历史价格刷新降级: {history_result.get('error', 'real provider unavailable')}。历史类比若依赖 synthetic_demo_price_path，只能用于 UI 演示。"
        confidence = 0.42
    new_id = insert_evidence_record(
        conn,
        symbol=symbol,
        claim=claim,
        source_type="historical_analogy",
        source_name=history_result.get("sourceName", "historical provider"),
        source_url=None,
        observed_at=observed_at,
        valid_until=valid_until,
        confidence=confidence,
        is_model_inferred=False,
    )
    mark_evidence_superseded(conn, evidence_ids=old_ids, superseded_by=new_id)
    return new_id


def insert_refresh_disclosure_evidence(
    *,
    conn: sqlite3.Connection,
    symbol: str,
    disclosure_result: dict[str, Any],
    observed_at: str,
    disclosure_valid_until: str,
    financial_valid_until: str,
) -> tuple[int, int]:
    old_disclosures = fetch_active_evidence_ids_by_type(conn, symbol=symbol, source_type="disclosure")
    old_financial = fetch_active_evidence_ids_by_type(conn, symbol=symbol, source_type="financial_report")
    filings = disclosure_result.get("filings", [])
    if disclosure_result.get("ok") and filings:
        latest = filings[0]
        disclosure_claim = f"{symbol} 权威披露刷新成功: 最近 {len(filings)} 条来自 {disclosure_result.get('sourceName')}。最新披露为 {latest.get('form')} {latest.get('filingDate')} {latest.get('primaryDocument')}。"
        financial_claim = f"{symbol} 财报/公告 evidence 来自 {disclosure_result.get('sourceName')}: {latest.get('form')} filed {latest.get('filingDate')}，report date {latest.get('reportDate') or 'n/a'}。"
        confidence = 0.88
        source_url = latest.get("url")
    else:
        disclosure_claim = f"{symbol} 权威披露刷新失败: {disclosure_result.get('error', 'unknown error')}。只能保留公告检索入口，不能作为已核验披露事实。"
        financial_claim = f"{symbol} 财报/公告 evidence 未能从权威 provider 拉取；财务结论必须降级或等待上传文档。"
        confidence = 0.34
        source_url = None
    disclosure_id = insert_evidence_record(
        conn,
        symbol=symbol,
        claim=disclosure_claim,
        source_type="disclosure",
        source_name=disclosure_result.get("sourceName", "disclosure provider"),
        source_url=source_url,
        observed_at=observed_at,
        valid_until=disclosure_valid_until,
        confidence=confidence,
        is_model_inferred=False,
    )
    financial_id = insert_evidence_record(
        conn,
        symbol=symbol,
        claim=financial_claim,
        source_type="financial_report",
        source_name=disclosure_result.get("sourceName", "disclosure provider"),
        source_url=source_url,
        observed_at=observed_at,
        valid_until=financial_valid_until,
        confidence=confidence,
        is_model_inferred=False,
    )
    mark_evidence_superseded(conn, evidence_ids=old_disclosures, superseded_by=disclosure_id)
    mark_evidence_superseded(conn, evidence_ids=old_financial, superseded_by=financial_id)
    return disclosure_id, financial_id
