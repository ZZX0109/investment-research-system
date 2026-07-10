from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Any, Callable

from .portfolio_repository import (
    delete_user_holding_rows,
    fetch_default_holding_rows,
    fetch_latest_user_holding_row,
    fetch_user_holding_rows,
    insert_user_holding_row,
    insert_user_holding_rows,
    upsert_user_profile,
)
from .schemas import PortfolioPayload


def preference_copy(preference: str) -> dict[str, str]:
    mapping = {
        "balanced": ("均衡模式", "同时关注收益来源、证据质量、集中度和历史风险分布。"),
        "conservative": ("稳健型", "优先显示回撤、集中度、波动率和估值高位风险。"),
        "growth": ("成长型", "优先显示营收增速、行业空间、利润率和长期叙事。"),
        "trading": ("短线型", "优先显示新闻事件、价格趋势、成交量和技术触发条件。"),
        "fund": ("基金型", "优先显示行业暴露、重仓股、风格漂移和指数相关性。"),
    }
    label, description = mapping[preference]
    return {"label": label, "description": description}


def build_user_holdings(
    user_id: int,
    *,
    connect: Callable[[], sqlite3.Connection],
    try_fetch_market_snapshot: Callable[[str, str], dict[str, Any]],
    build_source_meta: Callable[..., dict[str, Any]],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_user_holding_rows(conn, user_id)
    holdings: list[dict[str, Any]] = []
    for row in rows:
        snapshot = try_fetch_market_snapshot(row["symbol"], row["market"])
        live_price = float(snapshot["marketValueHint"]) if snapshot.get("ok") else float(row["cost_price"])
        market_value = live_price * float(row["shares"])
        source_meta = snapshot.get("sourceMeta") or build_source_meta(
            provider=snapshot["sourceName"],
            as_of=snapshot.get("observedAt", iso(now_utc())),
            overrides=[] if snapshot.get("ok") else ["manual_override", "fallback_cost_basis"],
            synthetic_ratio=0.0,
        )
        if snapshot.get("ok") and float(source_meta.get("synthetic_ratio", 0)) > 0:
            data_status = "synthetic"
        elif snapshot.get("ok"):
            data_status = "live"
        else:
            data_status = "fallback_cost_basis"
        holdings.append(
            {
                "symbol": row["symbol"],
                "name": row["name"],
                "market": row["market"],
                "sector": row["sector"],
                "shares": row["shares"],
                "costValue": round(float(row["shares"]) * float(row["cost_price"]), 2),
                "marketValue": round(market_value, 2),
                "weight": 0,
                "dayChange": float(snapshot["dayChange"]) if snapshot.get("ok") else 0,
                "dataSource": snapshot["sourceName"],
                "dataStatus": data_status,
                "observedAt": snapshot.get("observedAt", iso(now_utc())),
                "sourceMeta": source_meta,
            }
        )
    total = sum(item["marketValue"] for item in holdings) or 1
    for item in holdings:
        item["weight"] = round((item["marketValue"] / total) * 100, 2)
    return holdings


def build_default_holdings(*, connect: Callable[[], sqlite3.Connection]) -> list[dict[str, Any]]:
    with closing(connect()) as conn:
        rows = fetch_default_holding_rows(conn)
    total = sum(row["market_value"] for row in rows) or 1
    return [
        {
            "symbol": row["symbol"],
            "name": row["name"],
            "market": row["market"],
            "sector": row["sector"],
            "shares": row["shares"],
            "costValue": row["cost_value"],
            "marketValue": row["market_value"],
            "weight": round((row["market_value"] / total) * 100, 2),
            "dayChange": row["day_change"],
        }
        for row in rows
    ]


def clean_onboarding_holdings(
    holdings: list[dict[str, Any]],
    *,
    default_sector: Callable[[str, str], str],
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in holdings:
        symbol = str(item.get("symbol", "")).strip().upper()
        market = str(item.get("market", "us")).lower()
        shares = float(item.get("shares", 0) or 0)
        cost_price = float(item.get("costPrice", item.get("cost_price", 0)) or 0)
        if not symbol or market not in {"us", "cn"} or shares <= 0 or cost_price < 0:
            continue
        cleaned.append(
            {
                "symbol": symbol,
                "name": str(item.get("name") or symbol).strip() or symbol,
                "market": market,
                "sector": str(item.get("sector") or default_sector(symbol, market)).strip(),
                "shares": shares,
                "cost_price": cost_price,
            }
        )
    return cleaned


def save_onboarding_portfolio(
    *,
    user_id: int,
    preference: str,
    risk_answers: dict[str, Any],
    holdings: list[dict[str, Any]],
    connect: Callable[[], sqlite3.Connection],
    default_sector: Callable[[str, str], str],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    ensure_price_history: Callable[[sqlite3.Connection, str, str], Any],
    ensure_evidence: Callable[[sqlite3.Connection, sqlite3.Row], None],
    archive_expired_evidence: Callable[[sqlite3.Connection], None],
) -> list[dict[str, Any]]:
    cleaned = clean_onboarding_holdings(holdings, default_sector=default_sector)
    if not cleaned:
        raise ValueError("Add at least one valid holding.")

    updated_at = iso(now_utc())
    with connect() as conn:
        delete_user_holding_rows(conn, user_id)
        insert_user_holding_rows(conn, user_id=user_id, holdings=cleaned, updated_at=updated_at)
        upsert_user_profile(
            conn,
            user_id=user_id,
            preference=preference,
            risk_answers_json=json.dumps(risk_answers, ensure_ascii=False),
            onboarding_completed=True,
            updated_at=updated_at,
        )
        for item in cleaned:
            ensure_price_history(conn, item["symbol"], item["market"])
            row = fetch_latest_user_holding_row(conn, user_id=user_id, symbol=item["symbol"])
            if row is not None:
                ensure_evidence(conn, row)
        archive_expired_evidence(conn)
        conn.commit()
    return cleaned


def add_watchlist_holding(
    *,
    user_id: int,
    symbol: str,
    market: str,
    name: str | None,
    connect: Callable[[], sqlite3.Connection],
    try_fetch_market_snapshot: Callable[[str, str], dict[str, Any]],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    ensure_price_history: Callable[[sqlite3.Connection, str, str], Any],
    ensure_evidence: Callable[[sqlite3.Connection, sqlite3.Row], None],
) -> dict[str, Any]:
    normalized_symbol = symbol.strip().upper()
    normalized_market = market.strip().lower() or "us"
    snapshot = try_fetch_market_snapshot(normalized_symbol, normalized_market)
    with connect() as conn:
        existing = fetch_latest_user_holding_row(conn, user_id=user_id, symbol=normalized_symbol)
        if existing is None:
            cost_price = float(snapshot.get("marketValueHint")) if snapshot.get("ok") else 100.0
            insert_user_holding_row(
                conn,
                user_id=user_id,
                symbol=normalized_symbol,
                name=name or normalized_symbol,
                market=normalized_market,
                sector="新加入观察池",
                shares=1.0,
                cost_price=cost_price,
                updated_at=iso(now_utc()),
            )
        ensure_price_history(conn, normalized_symbol, normalized_market)
        row = fetch_latest_user_holding_row(conn, user_id=user_id, symbol=normalized_symbol)
        if row is not None:
            ensure_evidence(conn, row)
        conn.commit()
        holding = fetch_latest_user_holding_row(conn, user_id=user_id, symbol=normalized_symbol)
    if holding is None:
        raise LookupError(f"{normalized_symbol} could not be added to the watchlist.")
    return {"holding": dict(holding), "snapshot": snapshot}


def build_risk_radar(holdings: list[dict[str, Any]], preference: str) -> list[dict[str, Any]]:
    top_weight = max(item["weight"] for item in holdings)
    tech_weight = sum(item["weight"] for item in holdings if item["sector"] in {"AI 算力", "科技指数", "电动车"})
    avg_abs_change = sum(abs(item["dayChange"]) for item in holdings) / len(holdings)
    profile_boost = {"conservative": 1.16, "growth": 0.94, "trading": 1.08, "fund": 1.02, "balanced": 1.0}[preference]
    return [
        {"label": "集中度", "value": round(min(100, top_weight * 2.2 * profile_boost), 1)},
        {"label": "波动率", "value": round(min(100, avg_abs_change * 18 * profile_boost), 1)},
        {"label": "回撤风险", "value": round(min(100, (top_weight + avg_abs_change * 8) * profile_boost), 1)},
        {"label": "行业暴露", "value": round(min(100, tech_weight * 1.08), 1)},
        {"label": "事件风险", "value": round(min(100, 58 + avg_abs_change * 6), 1)},
    ]


def build_empty_portfolio(
    preference: str,
    *,
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    build_source_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "holdings": [],
        "portfolioCurve": [],
        "portfolioCurveSource": "no holdings",
        "sectorExposure": [],
        "metrics": {"marketValue": 0, "cost": 0, "todayPnl": 0, "totalReturn": 0, "topWeight": 0},
        "riskRadar": [],
        "preference": preference_copy(preference),
        "events": [
            {"title": "等待前测与持仓", "summary": "完成账户注册、偏好前测并录入至少一个持仓后，系统才会生成投研面板。", "tone": "warn"}
        ],
        "cacheStatus": {"label": "未生成用户组合", "asOf": iso(now_utc())},
        "sourceMeta": build_source_meta(
            provider="no_holdings",
            as_of=iso(now_utc()),
            overrides=["missing"],
            synthetic_ratio=0.0,
        ),
        "onboardingRequired": True,
    }
    return PortfolioPayload(**payload).model_dump()


def build_portfolio_payload(
    preference: str,
    *,
    user_id: int | None,
    get_user_holdings: Callable[[int], list[dict[str, Any]]],
    get_default_holdings: Callable[[], list[dict[str, Any]]],
    portfolio_curve_from_history: Callable[[list[dict[str, Any]]], list[float]],
    portfolio_curve_source_label: Callable[[list[dict[str, Any]]], str],
    build_source_meta: Callable[..., dict[str, Any]],
    current_data_mode: Callable[[], str],
    now_utc: Callable[[], datetime],
    iso: Callable[[datetime], str],
    synthetic_history_source: str,
    sector_colors: dict[str, str],
) -> dict[str, Any]:
    holdings = get_user_holdings(user_id) if user_id is not None else get_default_holdings()
    if not holdings:
        return build_empty_portfolio(preference, now_utc=now_utc, iso=iso, build_source_meta=build_source_meta)
    live_count = sum(1 for item in holdings if item.get("dataStatus") == "live")
    synthetic_ratios = [
        float(item.get("sourceMeta", {}).get("synthetic_ratio", 0))
        for item in holdings
        if isinstance(item.get("sourceMeta"), dict)
    ]
    holding_synthetic_ratio = max(synthetic_ratios or [0.0])
    total_value = sum(item["marketValue"] for item in holdings)
    total_cost = sum(item["costValue"] for item in holdings)
    today_pnl = sum(item["marketValue"] * item["dayChange"] / 100 for item in holdings)
    portfolio_curve = portfolio_curve_from_history(holdings)
    curve_source = portfolio_curve_source_label(holdings)
    sectors: dict[str, float] = {}
    for item in holdings:
        sectors[item["sector"]] = sectors.get(item["sector"], 0) + item["weight"]
    exposure = [{"name": key, "value": round(value, 1), "color": sector_colors.get(key, "#607d8b")} for key, value in sectors.items()]
    payload = {
        "holdings": holdings,
        "portfolioCurve": portfolio_curve,
        "portfolioCurveSource": curve_source,
        "sectorExposure": exposure,
        "metrics": {
            "marketValue": round(total_value, 2),
            "cost": round(total_cost, 2),
            "todayPnl": round(today_pnl, 2),
            "totalReturn": round(((total_value - total_cost) / total_cost) * 100, 2) if total_cost else 0,
            "topWeight": round(max(item["weight"] for item in holdings), 2),
        },
        "riskRadar": build_risk_radar(holdings, preference),
        "preference": preference_copy(preference),
        "events": [
            {"title": "证据链刷新", "summary": "行情、财报、新闻、历史类比和模型推断分开记录，并展示有效期。", "tone": "good"},
            {"title": "经验历史池", "summary": "过期证据不会删除，会归档为复盘样本。", "tone": "neutral"},
            {"title": "数据源状态", "summary": f"{live_count}/{len(holdings)} 个持仓当前来自实时行情接口；非 live 项不能作为最新市场事实。", "tone": "warn" if live_count < len(holdings) else "good"},
            {"title": "组合曲线说明", "summary": f"组合曲线按持仓份额和历史价格计算；当前历史源: {curve_source}。synthetic_demo_price_path 仅用于 UI 演示。", "tone": "warn" if synthetic_history_source in curve_source else "good"},
        ],
        "cacheStatus": {"label": f"行情源: {live_count}/{len(holdings)} live；组合曲线: {curve_source}", "asOf": iso(now_utc())},
        "sourceMeta": build_source_meta(
            provider=curve_source,
            as_of=iso(now_utc()),
            overrides=["synthetic"] if synthetic_history_source in curve_source or holding_synthetic_ratio > 0 else ([] if live_count == len(holdings) else ["manual_override"]),
            synthetic_ratio=1.0 if synthetic_history_source in curve_source else holding_synthetic_ratio,
            mode=current_data_mode() if holding_synthetic_ratio > 0 or synthetic_history_source in curve_source else None,
        ),
        "onboardingRequired": False,
    }
    return PortfolioPayload(**payload).model_dump()
