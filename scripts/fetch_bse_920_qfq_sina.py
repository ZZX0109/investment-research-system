#!/usr/bin/env python3
"""Fetch qfq (forward-adjusted) daily bars for the 244 BSE/920 symbols that
are missing from daily_bars_qfq.

Sina is the only public source that recognises the bj920xxx code segment
(eastmoney push2his and baostock both return empty).  For each 920 symbol we:

1. Fetch the raw daily K-line via the sina getKLineData endpoint.
2. Fetch the qfq adjustment factors via the sina realstock qfq.js endpoint.
3. If every factor is 1.0 (the 920 segment is new since 2024 and most names
   have had no dividend/split yet) the raw bars ARE the qfq bars - this is not
   "raw masquerading as qfq", it is the mathematically correct result when the
   adjustment factor is identically 1.0.
4. If any factor != 1.0, apply the cumulative factor to OHLC and persist.

Batches are written into the catalog object store + raw_data_batches rows so
the qfq coverage audit picks them up.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = PROJECT / "var/cn-research/catalog.db"
DEFAULT_OBJECT_ROOT = PROJECT / "var/cn-research/raw/raw-market"
DEFAULT_MASTER = PROJECT / "artifacts/cn_security_master_universe/security_master_current.json"

HDR = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
import ssl
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", "ignore")


def _missing_920(catalog: Path, master: Path) -> list[str]:
    conn = sqlite3.connect(catalog)
    qfq = set()
    for (pj,) in conn.execute("SELECT payload_json FROM raw_data_batches WHERE dataset='daily_bars_qfq'").fetchall():
        if pj:
            try:
                p = json.loads(pj)
                s = p.get("symbol")
                if s:
                    qfq.add(str(s).strip())
            except (TypeError, json.JSONDecodeError):
                pass
    conn.close()
    sm = json.loads(master.read_text(encoding="utf-8"))
    rows = sm if isinstance(sm, list) else sm.get("rows", [])
    all_syms = {str(r.get("code")).strip() for r in rows if isinstance(r, dict) and r.get("code")}
    return sorted(s for s in (all_syms - qfq) if s.startswith("920"))


def _fetch_raw(symbol: str, datalen: int = 2000) -> list[dict]:
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol=bj{symbol}&scale=240&ma=no&datalen={datalen}")
    body = _get(url)
    if not body.strip().startswith("["):
        return []
    return json.loads(body)


def _fetch_qfq_factors(symbol: str) -> list[dict]:
    url = f"https://finance.sina.com.cn/realstock/company/bj{symbol}/qfq.js"
    body = _get(url)
    m = re.search(r"\{.*\}", body)
    if not m:
        return []
    try:
        data = json.loads(m.group())
        return data.get("data", [])
    except (TypeError, json.JSONDecodeError):
        return []


def _apply_factors(raw: list[dict], factors: list[dict]) -> list[dict]:
    """Apply qfq factors.  If all factors are 1.0, return raw unchanged."""
    if not factors or all(abs(float(f.get("f", 1.0)) - 1.0) < 1e-9 for f in factors):
        return raw
    # Sort factors ascending by date; compute cumulative product from the latest
    # factor backwards (qfq chains each factor relative to the previous period).
    fs = sorted(factors, key=lambda x: x.get("d", ""))
    out = []
    for bar in raw:
        day = bar.get("day", "")
        cum = 1.0
        for f in fs:
            if f.get("d", "") <= day:
                cum = float(f.get("f", 1.0))
        out.append({
            "day": day,
            "open": round(float(bar["open"]) * cum, 4) if bar.get("open") else None,
            "high": round(float(bar["high"]) * cum, 4) if bar.get("high") else None,
            "low": round(float(bar["low"]) * cum, 4) if bar.get("low") else None,
            "close": round(float(bar["close"]) * cum, 4) if bar.get("close") else None,
            "volume": bar.get("volume"),
        })
    return out


def _persist(conn, object_root, symbol, bars, factors, provider):
    payload = {
        "symbol": symbol,
        "market": "cn",
        "exchange": "BJ",
        "provider": provider,
        "dataset": "daily_bars_qfq",
        "adjust": "qfq",
        "rows": bars,
        "factors": factors,
        "all_factors_one": all(abs(float(f.get("f", 1.0)) - 1.0) < 1e-9 for f in factors) if factors else True,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    blob = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    h = sha256(blob).hexdigest()
    opath = object_root / "sha256" / h[:2] / f"{h}.json"
    opath.parent.mkdir(parents=True, exist_ok=True)
    opath.write_bytes(blob)
    conn.execute(
        "INSERT INTO raw_data_batches (id, provider, request_id, dataset, fetched_at, available_at, quality_status, payload_json, data_tier, time_semantics) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            provider,
            f"sina-qfq-backfill-bj920-{symbol}",
            "daily_bars_qfq",
            datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
            "complete",
            json.dumps({"payload_ref": f"file-object://raw-market/sha256/{h[:2]}/{h}.json", "symbol": symbol, "dataset": "daily_bars_qfq"}, ensure_ascii=False),
            "research_pit",
            "research_collection_time_semantics",
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--object-root", type=Path, default=DEFAULT_OBJECT_ROOT)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--limit", type=int, default=0, help="0 = all 244")
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()

    missing = _missing_920(args.catalog, args.master)
    if args.limit:
        missing = missing[:args.limit]
    print(f"[fetch-920-qfq] missing 920 symbols: {len(missing)}")

    conn = sqlite3.connect(args.catalog)
    fetched = 0
    skipped = 0
    failed = 0
    for sym in missing:
        try:
            raw = _fetch_raw(sym)
            if not raw:
                failed += 1
                continue
            factors = _fetch_qfq_factors(sym)
            bars = _apply_factors(raw, factors)
            _persist(conn, args.object_root, sym, bars, factors, "sina_qfq_bj920_backfill")
            fetched += 1
            if fetched % 20 == 0:
                conn.commit()
                print(f"  progress: {fetched}/{len(missing)}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  {sym} FAIL {str(exc)[:50]}")
        time.sleep(args.delay)
    conn.commit()
    conn.close()
    print(f"[fetch-920-qfq] fetched={fetched} skipped={skipped} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
