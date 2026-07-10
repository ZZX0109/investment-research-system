from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import timedelta
from typing import Any, Callable

from .refresh_repository import (
    count_experience_history,
    fetch_default_holding_rows,
    fetch_user_refresh_holding_rows,
    insert_refresh_items,
    insert_refresh_run,
    update_default_holding_market_values,
)
from .schemas import RefreshPayload


def dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def claim_status_map(graph: dict[str, Any]) -> dict[str, str]:
    return {item["id"]: item["status"] for item in graph.get("claims", [])}


def summarize_claim_status_change(before: dict[str, str], after: dict[str, str]) -> list[str]:
    changes = []
    for claim_id in sorted(set(before) | set(after)):
        if before.get(claim_id) != after.get(claim_id):
            changes.append(f"{claim_id}: {before.get(claim_id, 'missing')} -> {after.get(claim_id, 'missing')}")
    return changes


def build_refresh_review_for_symbol(
    *,
    user_id: int,
    holding_row: sqlite3.Row,
    snapshot: dict[str, Any],
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], Any],
    iso: Callable[[Any], str],
    get_user_holdings: Callable[[int], list[dict[str, Any]]],
    get_evidence: Callable[[str], list[dict[str, Any]]],
    latest_document_analysis: Callable[[str], dict[str, Any]],
    get_historical_analogies: Callable[[str], list[dict[str, Any]]],
    research_text: Callable[[str, str, str, str], dict[str, Any]],
    build_evidence_graph: Callable[..., dict[str, Any]],
    compute_risk_score: Callable[[str, list[dict[str, Any]], list[dict[str, Any]]], float],
    try_fetch_news_events: Callable[[str, str], dict[str, Any]],
    try_fetch_disclosures: Callable[[str, str], dict[str, Any]],
    ensure_price_history: Callable[[sqlite3.Connection, str, str | None], dict[str, Any]],
    ensure_evidence: Callable[[sqlite3.Connection, sqlite3.Row], None],
    archive_expired_evidence: Callable[[sqlite3.Connection], None],
    insert_refresh_market_evidence: Callable[..., int],
    insert_refresh_history_evidence: Callable[..., int],
    insert_refresh_news_evidence: Callable[..., int],
    insert_refresh_disclosure_evidence: Callable[..., tuple[int, int]],
    research_quality_audit: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    symbol = holding_row["symbol"]
    before_holding = next((item for item in get_user_holdings(user_id) if item["symbol"] == symbol), None)
    before_evidence = get_evidence(symbol)
    before_doc = latest_document_analysis(symbol)
    before_analogies = get_historical_analogies(symbol)
    before_text = research_text(symbol, holding_row["name"], holding_row["sector"], "balanced")
    before_graph = build_evidence_graph(before_evidence, before_holding or dict(holding_row), before_doc, before_analogies)
    before_score = compute_risk_score(before_text["riskLevel"], before_evidence, before_analogies)
    news_result = try_fetch_news_events(symbol, holding_row["market"])
    disclosure_result = try_fetch_disclosures(symbol, holding_row["market"])

    observed = now_utc()
    with closing(connect()) as conn:
        new_market_evidence_id = insert_refresh_market_evidence(
            conn=conn,
            symbol=symbol,
            snapshot=snapshot,
            observed_at=iso(observed),
            valid_until=iso(observed + timedelta(days=1)),
        )
        history_result = ensure_price_history(conn, symbol, holding_row["market"])
        new_history_evidence_id = insert_refresh_history_evidence(
            conn=conn,
            symbol=symbol,
            history_result=history_result,
            observed_at=iso(observed),
            valid_until=iso(observed + timedelta(days=1)),
        )
        new_news_evidence_id = insert_refresh_news_evidence(
            conn=conn,
            symbol=symbol,
            news_result=news_result,
            observed_at=iso(observed),
            valid_until=iso(observed + timedelta(hours=24)),
        )
        new_disclosure_evidence_id, new_financial_evidence_id = insert_refresh_disclosure_evidence(
            conn=conn,
            symbol=symbol,
            disclosure_result=disclosure_result,
            observed_at=iso(observed),
            disclosure_valid_until=iso(observed + timedelta(days=7)),
            financial_valid_until=iso(observed + timedelta(days=90)),
        )
        ensure_evidence(conn, holding_row)
        history_count_before = count_experience_history(conn, symbol)
        archive_expired_evidence(conn)
        history_count_after = count_experience_history(conn, symbol)
        conn.commit()

    after_holding = next((item for item in get_user_holdings(user_id) if item["symbol"] == symbol), None)
    after_evidence = get_evidence(symbol)
    after_doc = latest_document_analysis(symbol)
    after_analogies = get_historical_analogies(symbol)
    after_text = research_text(symbol, holding_row["name"], holding_row["sector"], "balanced")
    after_graph_base = build_evidence_graph(after_evidence, after_holding or dict(holding_row), after_doc, after_analogies)
    after_audit = research_quality_audit(
        after_evidence,
        symbol,
        holding_row["market"],
        after_doc,
        after_analogies,
        has_bear_case=True,
        claim_graph=after_graph_base,
    )
    after_graph = build_evidence_graph(after_evidence, after_holding or dict(holding_row), after_doc, after_analogies, after_audit)
    after_score = compute_risk_score(after_text["riskLevel"], after_evidence, after_analogies)
    evidence_changes = {
        "newEvidenceIds": [new_market_evidence_id, new_history_evidence_id, new_news_evidence_id, new_disclosure_evidence_id, new_financial_evidence_id],
        "archivedCount": max(0, history_count_after - history_count_before),
        "expiredEvidenceIds": after_graph["expiredEvidenceIds"],
        "supersededMarketEvidence": [item["id"] for item in before_evidence if item["sourceType"] == "market_data"],
        "supersededHistoryEvidence": [item["id"] for item in before_evidence if item["sourceType"] == "historical_analogy"],
        "supersededNewsEvidence": [item["id"] for item in before_evidence if item["sourceType"] == "news_event"],
        "supersededDisclosureEvidence": [item["id"] for item in before_evidence if item["sourceType"] == "disclosure"],
        "supersededFinancialEvidence": [item["id"] for item in before_evidence if item["sourceType"] == "financial_report"],
    }
    conclusion_changes = summarize_claim_status_change(claim_status_map(before_graph), claim_status_map(after_graph))
    return {
        "symbol": symbol,
        "beforeScore": before_score,
        "afterScore": after_score,
        "riskScoreDelta": round(after_score - before_score, 1),
        "beforeClaimSummary": before_graph["summary"],
        "afterClaimSummary": after_graph["summary"],
        "evidenceChanges": evidence_changes,
        "conclusionChanges": conclusion_changes or ["claim 状态未变化；刷新只更新了证据版本和时间戳。"],
        "snapshotStatus": "live" if snapshot.get("ok") else "degraded",
        "snapshot": snapshot,
        "news": news_result,
        "historySource": history_result,
        "disclosure": disclosure_result,
    }


def build_refresh_user_data(
    *,
    user_id: int,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], Any],
    iso: Callable[[Any], str],
    try_fetch_market_snapshot: Callable[[str, str], dict[str, Any]],
    refresh_review_for_symbol: Callable[[int, sqlite3.Row, dict[str, Any]], dict[str, Any]],
    get_experience_history: Callable[[str | None], list[dict[str, Any]]],
) -> dict[str, Any]:
    refreshed_at = iso(now_utc())
    refresh_id = f"refresh-{user_id}-{now_utc().strftime('%Y%m%d%H%M%S%f')}"
    with closing(connect()) as conn:
        rows = fetch_user_refresh_holding_rows(conn, user_id)
    refreshed = [refresh_review_for_symbol(user_id, holding, try_fetch_market_snapshot(holding["symbol"], holding["market"])) for holding in rows]
    archived_count = sum(item["evidenceChanges"]["archivedCount"] for item in refreshed)
    summary = f"刷新 {len(refreshed)} 个标的，归档 {archived_count} 条过期证据。"
    with closing(connect()) as conn:
        insert_refresh_run(
            conn,
            refresh_id=refresh_id,
            user_id=user_id,
            refreshed_at=refreshed_at,
            symbol_count=len(refreshed),
            archived_count=archived_count,
            summary=summary,
        )
        insert_refresh_items(conn, refresh_id=refresh_id, items=refreshed)
        conn.commit()
    return dump_model(
        RefreshPayload(
            ok=True,
            refreshId=refresh_id,
            refreshedAt=refreshed_at,
            count=len(refreshed),
            summary=summary,
            items=refreshed,
            history=get_experience_history(),
        )
    )


def build_default_refresh_data(
    *,
    connect: Callable[[], sqlite3.Connection],
    now_utc: Callable[[], Any],
    iso: Callable[[Any], str],
    try_fetch_market_snapshot: Callable[[str, str], dict[str, Any]],
    ensure_price_history: Callable[[sqlite3.Connection, str, str | None], dict[str, Any]],
    ensure_evidence: Callable[[sqlite3.Connection, sqlite3.Row], None],
    archive_expired_evidence: Callable[[sqlite3.Connection], None],
    get_experience_history: Callable[[str | None], list[dict[str, Any]]],
) -> dict[str, Any]:
    refreshed: list[dict[str, Any]] = []
    with closing(connect()) as conn:
        rows = fetch_default_holding_rows(conn)
        for holding in rows:
            snapshot = try_fetch_market_snapshot(holding["symbol"], holding["market"])
            if snapshot.get("ok"):
                update_default_holding_market_values(
                    conn,
                    symbol=holding["symbol"],
                    market_value=float(snapshot["marketValueHint"]) * float(holding["shares"]),
                    day_change=float(snapshot["dayChange"]),
                )
            ensure_price_history(conn, holding["symbol"], holding["market"])
            ensure_evidence(conn, holding)
            refreshed.append({"symbol": holding["symbol"], "market": holding["market"], "snapshot": snapshot})
        archive_expired_evidence(conn)
        conn.commit()
    return dump_model(
        RefreshPayload(
            ok=True,
            refreshedAt=iso(now_utc()),
            count=len(refreshed),
            items=refreshed,
            history=get_experience_history(),
        )
    )
