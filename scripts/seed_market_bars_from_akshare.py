"""§6 ② + §1 data-root unblock — fetch REAL historical daily bars from akshare's
``stock_zh_a_hist`` (qfq-adjusted) + persist them as ``VersionedMarketBar``
rows in ``versioned_market_bars`` (currently empty). This removes the
"PreparedPriceBar not persisted / no stored daily closes" data-root blocker
for §1 row-2 (CatBoost 1/5/20d labels) + Step 4 (retrain long-term model).

Round 17 found akshare kline gated (network_unavailable); round 26 confirmed
the endpoint NOW WORKS (242 bars for 600519 in 2024) — so this seeds real
closes. Idempotent via add_bar's revision-immutable dedup.

Usage:
    NODE_ENV=development python3 -m scripts.seed_market_bars_from_akshare 600519
    NODE_ENV=development python3 -m scripts.seed_market_bars_from_akshare --all
"""
from __future__ import annotations

import argparse
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from investment_research.domain.trusted_market import RawDataBatch, VersionedMarketBar
from investment_research.repository.sqlite import SQLiteUnitOfWork, get_default_database_path

log = logging.getLogger("seed_bars")


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def _calendar_for(symbol: str) -> str:
    # 6xxxxx → XSHG (Shanghai), 0xxxxx/3xxxxx → XSHE (Shenzhen).
    return "XSHE" if symbol.startswith(("0", "3")) else "XSHG"


def _prefix_for(symbol: str) -> str:
    # stock_zh_a_daily (SINA) needs the sh/sz prefix.
    return "sz" if symbol.startswith(("0", "3")) else "sh"


def _seed_symbol(repo, symbol: str, *, start: str, end: str) -> int:
    try:
        import akshare as ak

        # SINA-based stock_zh_a_daily (reliable; eastmoney stock_zh_a_hist is flaky
        # with ProxyError to push2his.eastmoney.com). English cols: date/open/...
        df = ak.stock_zh_a_daily(symbol=f"{_prefix_for(symbol)}{symbol}", start_date=start, end_date=end, adjust="qfq")
    except Exception as exc:  # pragma: no cover - network / akshare gated
        log.warning("kline skip %s: %s", symbol, str(exc)[:100])
        return 0
    if df is None or len(df) == 0:
        return 0
    fetched_at = datetime.now(timezone.utc)
    raw_payload = df.to_json(orient="records", date_format="iso").encode("utf-8")
    batch = RawDataBatch(
        provider="akshare/stock_zh_a_daily",
        request_id=f"kline-{symbol}-{start}-{end}",
        dataset="cn_a_daily_qfq",
        payload_ref="inmemory:kline",
        payload_hash=hashlib.sha256(raw_payload).hexdigest(),
        schema_version="1.0",
        symbol=symbol, interval="1d",
        coverage_start=datetime.fromisoformat(str(df.iloc[0]["date"])).replace(tzinfo=timezone.utc) if len(df) else None,
        coverage_end=datetime.fromisoformat(str(df.iloc[-1]["date"])).replace(tzinfo=timezone.utc) if len(df) else None,
        fetched_at=fetched_at, available_at=fetched_at,
        time_semantics="research_collection_time_semantics",
        data_tier="research_pit",
    )
    repo.add_raw_batch(batch)
    cal = _calendar_for(symbol)
    n = 0
    for _, row in df.iterrows():
        d = row["date"]
        try:
            trade_date = d if hasattr(d, "year") else datetime.strptime(str(d), "%Y-%m-%d").date()
        except Exception:
            continue
        bar_start = datetime(trade_date.year, trade_date.month, trade_date.day, tzinfo=timezone.utc)
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        if not (o > 0 and h > 0 and l > 0 and c > 0):
            continue
        bar = VersionedMarketBar(
            raw_batch_id=batch.id, symbol=symbol, provider="akshare/stock_zh_a_daily",
            interval="1d", bar_start=bar_start, trade_date=trade_date, calendar_code=cal,
            adjustment_mode="qfq", open=o, high=h, low=l, close=c,
            volume=float(row.get("volume") or 0) or None,
            amount=float(row.get("amount") or 0) or None,
            turnover_rate=float(row.get("turnover") or 0) or None,
            source_time=bar_start, ingest_time=fetched_at, available_at=fetched_at, as_of=bar_start,
            normalized_hash=_hash(symbol, trade_date.isoformat(), o, h, l, c, "qfq"),
        )
        try:
            repo.add_bar(bar)
            n += 1
        except ValueError:
            pass  # already stored (immutable revision) — idempotent
    return n


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol", nargs="?", default="600519")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--start", default="20200101")
    parser.add_argument("--end", default="20241231")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    db = get_default_database_path()
    uow = SQLiteUnitOfWork(db)
    repo = uow.trusted_market  # TrustedMarketRepository
    try:
        if args.all:
            cur = uow.connection.cursor()
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
            n = _seed_symbol(repo, sym, start=args.start, end=args.end)
            total += n
            if i % 10 == 0 or i == len(symbols):
                log.info("progress %d/%d symbols, %d bars stored", i, len(symbols), total)
        print(f"stored {total} daily bars across {len(symbols)} symbols from akshare kline")
    finally:
        uow.close()


if __name__ == "__main__":
    main()
