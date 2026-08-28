#!/usr/bin/env python3
"""Refresh recent daily bars (raw + qfq) for stale symbols whose latest
trade date lags behind the as-of date by more than 1 trading day.

Uses sina getKLineData (the only public source that reliably serves all
SH/SZ/BJ code segments after the eastmoney push2his outage).  For each stale
symbol we fetch the last 10 trading days of raw OHLCV and the qfq adjustment
factors; when every factor is 1.0 the raw bars ARE the qfq bars, otherwise we
apply the cumulative factor.  Incremental batches are persisted into the
catalog object store + raw_data_batches rows so the freshness audit picks up
the new date_end.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.request
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = PROJECT / "var/cn-research/catalog.db"
DEFAULT_OBJECT_ROOT = PROJECT / "var/cn-research/raw/raw-market"
DEFAULT_MANIFEST = PROJECT / "artifacts/download_manifests/latest.json"

HDR = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
import ssl
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def _sina_prefix(code: str) -> str:
    if code.startswith("6"):
        return "sh"
    if code.startswith(("0", "3")):
        return "sz"
    if code.startswith(("8", "4", "9")):
        return "bj"
    return "sh"


def _get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", "ignore")


def _stale_symbols(manifest: Path) -> list[str]:
    m = json.loads(manifest.read_text(encoding="utf-8"))
    recs = [r for r in m.get("records", []) if r.get("category") == "prices" and r.get("date_end")]
    sym_max: dict[str, str] = defaultdict(str)
    for r in recs:
        s = str(r.get("symbol") or "")
        de = str(r.get("date_end"))[:10]
        if de > sym_max[s]:
            sym_max[s] = de
    # stale = max date_end < 2026-08-23 (lag > 1 trading day from 2026-08-25)
    return sorted(s for s, de in sym_max.items() if de < "2026-08-23")


def _fetch_raw(symbol: str, datalen: int = 10) -> list[dict]:
    prefix = _sina_prefix(symbol)
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={prefix}{symbol}&scale=240&ma=no&datalen={datalen}")
    body = _get(url)
    if not body.strip().startswith("["):
        return []
    return json.loads(body)


def _fetch_qfq_factors(symbol: str) -> list[dict]:
    prefix = _sina_prefix(symbol)
    url = f"https://finance.sina.com.cn/realstock/company/{prefix}{symbol}/qfq.js"
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
    if not factors or all(abs(float(f.get("f", 1.0)) - 1.0) < 1e-9 for f in factors):
        return raw
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


def _persist(conn, object_root, symbol, bars, factors, dataset, provider):
    if not bars:
        return False
    date_end = max(b["day"] for b in bars if b.get("day"))
    date_start = min(b["day"] for b in bars if b.get("day"))
    payload = {
        "symbol": symbol,
        "market": "cn",
        "provider": provider,
        "dataset": dataset,
        "adjust": "qfq" if "qfq" in dataset else "raw",
        "rows": bars,
        "factors": factors,
        "date_start": date_start,
        "date_end": date_end,
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
            f"sina-refresh-{symbol}-{dataset}",
            dataset,
            datetime.now(timezone.utc).isoformat(),
            datetime.now(timezone.utc).isoformat(),
            "complete",
            json.dumps({"payload_ref": f"file-object://raw-market/sha256/{h[:2]}/{h}.json", "symbol": symbol, "dataset": dataset, "date_end": date_end}, ensure_ascii=False),
            "research_pit",
            "research_collection_time_semantics",
        ),
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--object-root", type=Path, default=DEFAULT_OBJECT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--offset", type=int, default=0, help="skip first N stale symbols")
    parser.add_argument("--delay", type=float, default=0.2)
    parser.add_argument("--raw-only", action="store_true", help="skip qfq (freshness only needs raw date_end)")
    args = parser.parse_args()

    stale = _stale_symbols(args.manifest)
    if args.offset:
        stale = stale[args.offset:]
    if args.limit:
        stale = stale[: args.limit]
    print(f"[refresh-daily] stale symbols: {len(stale)} raw_only={args.raw_only}")

    conn = sqlite3.connect(args.catalog)
    fetched = 0
    failed = 0
    for sym in stale:
        try:
            raw = _fetch_raw(sym)
            if not raw:
                failed += 1
                continue
            factors = [] if args.raw_only else _fetch_qfq_factors(sym)
            qfq_bars = _apply_factors(raw, factors)
            ok_r = _persist(conn, args.object_root, sym, raw, [], "daily_bars_raw", "sina_refresh")
            ok_q = False if args.raw_only else _persist(conn, args.object_root, sym, qfq_bars, factors, "daily_bars_qfq", "sina_refresh")
            if ok_r or ok_q:
                fetched += 1
            if fetched % 50 == 0 and fetched:
                conn.commit()
                print(f"  progress: {fetched}/{len(stale)}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            if failed <= 5:
                print(f"  {sym} FAIL {str(exc)[:50]}")
        time.sleep(args.delay)
    conn.commit()
    conn.close()
    print(f"[refresh-daily] fetched={fetched} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
