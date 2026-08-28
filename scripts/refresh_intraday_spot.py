"""Round 33 — intraday spot poller (manual verification step).

Fetches the full A-share spot snapshot + the three major indices (上证综指/
深证成指/创业板指) via akshare, skips off-hours unless ``--force``, and writes
a JSON artifact so the fetch path is verifiable before wiring it into the
scheduler + API + frontend board.

NOT a tick push stream — akshare is request/response; this is the latest spot
snapshot, intended to be polled hourly during CN trading sessions.

Usage::

    NODE_ENV=development python3 -m scripts.refresh_intraday_spot
    NODE_ENV=development python3 -m scripts.refresh_intraday_spot --force  # off-hours too
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from investment_research.integrations.xystock.quote_fetcher import (
    fetch_etf_spot,
    fetch_index_spot,
    fetch_market_spot,
    is_cn_trading_session,
)

_INDEX_CODES = ["000001", "399001", "399006"]  # 上证综指 / 深证成指 / 创业板指
_OUT_DIR = Path("artifacts/market")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="fetch even outside trading hours")
    args = parser.parse_args()

    now = datetime.now()
    in_session = is_cn_trading_session(now)
    print(f"[spot] now={now.isoformat()} trading_session={in_session}")
    if not in_session and not args.force:
        print("[spot] off-hours — skipping (use --force to fetch anyway)")
        return 0

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = now.strftime("%Y%m%dT%H%M%S")

    mk = fetch_market_spot()
    print(f"[market_spot] status={mk.status} ok={mk.ok} rows={len(mk.data) if mk.data else 0} err={mk.error}")
    if mk.data:
        sample = mk.data[0]
        print(f"  sample: {sample['symbol']} {sample.get('name')} price={sample.get('latest_price')} chg%={sample.get('change_pct')}")

    idx = fetch_index_spot(_INDEX_CODES)
    print(f"[index_spot] status={idx.status} ok={idx.ok} rows={len(idx.data) if idx.data else 0} err={idx.error}")
    if idx.data:
        for r in idx.data:
            print(f"  {r['symbol']} {r.get('name')} price={r.get('latest_price')} chg%={r.get('change_pct')}")

    etf = fetch_etf_spot(["510050", "510300", "510500", "159915", "512100", "518880"])
    print(f"[etf_spot] status={etf.status} ok={etf.ok} rows={len(etf.data) if etf.data else 0} err={etf.error}")

    artifact = {
        "captured_at": now.isoformat(),
        "trading_session": in_session,
        "market_spot": {
            "status": mk.status, "n_rows": len(mk.data) if mk.data else 0,
            "error": mk.error, "degraded": mk.degraded,
            "sample": mk.data[:3] if mk.data else [],
        },
        "index_spot": {
            "status": idx.status, "rows": idx.data or [], "error": idx.error,
        },
        "etf_spot": {
            "status": etf.status, "rows": etf.data or [], "error": etf.error,
        },
    }
    out = _OUT_DIR / f"intraday_spot_{ts}.json"
    out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[spot] wrote {out}")
    return 0 if (mk.ok or idx.ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
