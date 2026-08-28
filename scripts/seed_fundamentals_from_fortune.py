"""§6 ③ — populate real fundamental ``line_items`` from the fortune
``stock_financial_analysis_indicator`` adapter (integrations/fortune/
data_services/fundamental.py), so the snapshot's per-asset
``fundamental_coverage`` reflects REAL market data (roe/roa/net_margin/
profit_growth) rather than only the demo seed's revenue/net_profit/
gross_margin.

The fortune adapter returns INDICATOR RATIOS (roe%, roa%, net_margin%, …),
not absolute statement items, so this seeds the ratio pillars
(gross_margin/roe/roa/net_margin) — revenue/net_profit/operating_profit
(absolutes) still come from the statement-seed path. Idempotent: re-running
supersedes (does not duplicate) via the knowledge service's revision logic.

Usage:
    NODE_ENV=development python3 -m scripts.seed_fundamentals_from_fortune 600519
    NODE_ENV=development python3 -m scripts.seed_fundamentals_from_fortune --all
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

from investment_research.domain.knowledge import FinancialLineItem
from investment_research.integrations.fortune.data_services.fundamental import fetch_fundamentals
from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path
from investment_research.service.financial_knowledge import FinancialKnowledgeService

# Map the fortune adapter's feature keys -> the §6③ canonical pillar names
# the fundamental_coverage gate checks. Only RATIO pillars (the indicator
# endpoint returns ratios, not absolutes); revenue/net_profit/operating_profit
# are statement absolutes seeded separately.
_RATIO_PILLARS = {
    "gross_margin": ("gross_margin", "毛利率", "ratio"),
    "roe": ("roe", "净资产收益率", "%"),
    "roa": ("roa", "总资产报酬率", "%"),
    "net_margin": ("net_margin", "销售净利率", "%"),
}

log = logging.getLogger("seed_fundamentals")


# Statement absolutes (营业利润/营业收入/净利润) from the SINA income-statement
# endpoint — these are the ABSOLUTE pillars the indicator endpoint can't give
# (operating_profit especially). Values come back in 元 → convert to 亿元.
_STATEMENT_PILLARS = {
    "营业利润": ("operating_profit", "营业利润"),
    "营业收入": ("revenue", "营业收入"),
    "净利润": ("net_profit", "净利润"),
}


def _seed_statements(service: FinancialKnowledgeService, symbol: str, as_of: datetime) -> int:
    """Ingest REAL statement absolutes (operating_profit/revenue/net_profit)
    from akshare's SINA income-statement endpoint as line_items — closes the
    last 1/6 gap (operating_profit) with real market data, not demo seed."""
    try:
        import akshare as ak

        df = ak.stock_financial_report_sina(stock=symbol, symbol="利润表")
    except Exception as exc:  # pragma: no cover - network / akshare gated
        log.warning("statements skip %s: %s", symbol, str(exc)[:80])
        return 0
    if df is None or len(df) == 0:
        return 0
    latest = df.iloc[0]
    cols = {str(c) for c in df.columns}
    n = 0
    for cn_key, (pillar, label) in _STATEMENT_PILLARS.items():
        col = next((c for c in cols if cn_key in c), None)
        if not col:
            continue
        raw = latest.get(col)
        try:
            yuan = float(str(raw).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        if yuan != yuan:  # NaN
            continue
        value_yi = yuan / 1e8  # 元 → 亿元 (consistency with the demo seed unit)
        hash_kwargs = dict(
            symbol=symbol, period="2024FY", metric=pillar,
            source_url=f"https://akshare/stock_financial_report_sina/{symbol}",
            value=value_yi, unit="亿元", scale=1.0, published_at=as_of, metric_label=label,
        )
        item = FinancialLineItem(
            market="CN", yoy_pct=None, source_name="akshare/sina-report",
            available_at=as_of, valid_from=as_of,
            content_hash=FinancialLineItem.content_hash_of(**hash_kwargs), **hash_kwargs,
        )
        service.ingest_line_item(item)
        n += 1
    return n


def _seed_symbol(service: FinancialKnowledgeService, symbol: str, as_of: datetime) -> int:
    result = fetch_fundamentals(symbol)
    if result.status != "ok" or not result.data:
        log.warning("skip %s: status=%s degraded=%s err=%s", symbol, result.status, result.degraded, str(result.error)[:80])
    else:
        published = as_of
        n = 0
        for feat_key, (pillar, label, unit) in _RATIO_PILLARS.items():
            value = result.data.get(feat_key)
            if value is None:
                continue
            hash_kwargs = dict(
                symbol=symbol, period="2025FY", metric=pillar,
                source_url=f"https://akshare/stock_financial_analysis_indicator/{symbol}",
                value=float(value), unit=unit, scale=1.0, published_at=published, metric_label=label,
            )
            item = FinancialLineItem(
                market="CN", yoy_pct=None, source_name="akshare/fortune",
                available_at=published, valid_from=published,
                content_hash=FinancialLineItem.content_hash_of(**hash_kwargs), **hash_kwargs,
            )
            service.ingest_line_item(item)
            n += 1
        if n:
            log.info("%s: %d ratio line_items ingested", symbol, n)
    # Statement absolutes (operating_profit/revenue/net_profit) from SINA —
    # closes the 6/6 gap with real data.
    n_statements = _seed_statements(service, symbol, as_of)
    if n_statements:
        log.info("%s: %d statement line_items ingested", symbol, n_statements)
    return n + n_statements if (result.status == "ok" and result.data) else n_statements


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?", default="600519")
    parser.add_argument("--all", action="store_true", help="seed every CN asset in the db")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    db = get_default_database_path()
    uow = SQLiteUnitOfWork(db)
    service = FinancialKnowledgeService(uow)
    as_of = datetime(2025, 8, 30, tzinfo=timezone.utc)
    try:
        if args.all:
            cur = uow.connection.cursor()
            # assets table is event-sourced: ticker lives in the payload JSON.
            cur.execute(
                "SELECT DISTINCT json_extract(payload, '$.ticker') FROM assets "
                "WHERE status='active' AND json_extract(payload, '$.ticker') IS NOT NULL"
            )
            symbols = [r[0] for r in cur.fetchall() if r[0]]
            cur.close()
        else:
            symbols = [args.symbol]
        total = 0
        for i, sym in enumerate(symbols, 1):
            n = _seed_symbol(service, sym, as_of)
            total += n
            if i % 10 == 0 or i == len(symbols):
                log.info("progress %d/%d symbols, %d line_items ingested", i, len(symbols), total)
        print(f"seeded {total} fundamental line_items across {len(symbols)} symbols from fortune")
    finally:
        uow.close()


if __name__ == "__main__":
    main()
