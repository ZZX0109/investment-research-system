#!/usr/bin/env python3
"""Audit whether the daily CN research collection is current and complete.

Designed for a post-close cron/launchd/worker health probe.  It performs no
network request and does not mutate raw data: it only reads the coverage ledger
and persistent cursors, writes an atomic health artifact, and returns a
non-zero exit code when the collection requires attention.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=PROJECT / "artifacts/free_research_coverage.json")
    parser.add_argument("--cursor-store", type=Path, default=PROJECT / "var/cn-research/cursors.json")
    parser.add_argument("--output", type=Path, default=PROJECT / "artifacts/research_lifecycle/daily-data-health.json")
    parser.add_argument("--worker-heartbeat", type=Path, default=PROJECT / "artifacts/research_lifecycle/research-worker-heartbeat.json")
    parser.add_argument("--maximum-heartbeat-age-seconds", type=int, default=120)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--maximum-age-trading-days", type=int, default=1)
    return parser.parse_args()


def latest_completed_weekday(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def trading_day_age(source: date, expected: date) -> int:
    if source >= expected:
        return 0
    result = 0
    while source < expected:
        source += timedelta(days=1)
        if source.weekday() < 5:
            result += 1
    return result


def build_health(
    coverage: dict,
    cursors: dict,
    *,
    as_of: date,
    maximum_age_trading_days: int,
    worker_heartbeat: dict | None = None,
    maximum_heartbeat_age_seconds: int = 120,
) -> dict:
    expected = latest_completed_weekday(as_of)
    cn = next((row for row in coverage.get("market_coverage", []) if row.get("market") == "cn"), {})
    records = [
        row for row in cn.get("records", [])
        if row.get("dataset") in {"daily_bars_raw", "daily_bars_qfq"} and row.get("symbol")
    ]
    required_pairs = {(str(row["symbol"]), str(row["dataset"]).removeprefix("daily_bars_")) for row in records}
    cursor_by_pair: dict[tuple[str, str], list[dict]] = {}
    for raw in cursors.values():
        if not isinstance(raw, dict):
            continue
        symbol, mode = raw.get("symbol"), raw.get("adjustment_mode")
        if symbol and mode:
            cursor_by_pair.setdefault((str(symbol), str(mode)), []).append(raw)
    missing: list[str] = []
    stale: list[dict] = []
    invalid_dates: list[dict] = []
    fresh = 0
    for symbol, mode in sorted(required_pairs):
        values = cursor_by_pair.get((symbol, mode), [])
        parsed: list[tuple[date, dict]] = []
        for value in values:
            try:
                parsed.append((date.fromisoformat(str(value["last_successful_trade_date"])), value))
            except (KeyError, TypeError, ValueError):
                continue
        if not parsed:
            missing.append(f"{symbol}:{mode}")
            continue
        latest_date, latest_cursor = max(parsed, key=lambda item: item[0])
        if latest_date.weekday() >= 5:
            invalid_dates.append({"symbol": symbol, "adjustment_mode": mode, "last_successful_trade_date": latest_date.isoformat(), "provider": latest_cursor.get("provider")})
            continue
        age = trading_day_age(latest_date, expected)
        if age > maximum_age_trading_days:
            stale.append({"symbol": symbol, "adjustment_mode": mode, "last_successful_trade_date": latest_date.isoformat(), "age_trading_days": age, "provider": latest_cursor.get("provider")})
            continue
        fresh += 1
    coverage_ratio = float(cn.get("coverage_ratio", 0.0) or 0.0)
    event_status = str(cn.get("event_coverage_status", "unknown"))
    reasons: list[str] = []
    warnings: list[str] = []
    if not required_pairs:
        reasons.append("cn_price_coverage_records_missing")
    if coverage_ratio < 0.98:
        reasons.append("coverage_ratio_below_98pct")
    if missing:
        reasons.append("cursor_missing")
    if stale:
        reasons.append("cursor_stale")
    if invalid_dates:
        reasons.append("cursor_non_trading_date")
    # CNInfo is intentionally a rolling public-notice window.  ``partial``
    # means the limitation is disclosed, not that the completed daily price
    # update should be treated as failed.  Unknown/failed event coverage is
    # still a blocking collection problem.
    if event_status == "partial":
        warnings.append("event_coverage:partial")
    elif event_status not in {"events_present", "confirmed_none"}:
        reasons.append(f"event_coverage:{event_status}")
    heartbeat = worker_heartbeat or {}
    heartbeat_age_seconds = None
    try:
        observed_at = datetime.fromisoformat(str(heartbeat["observed_at"]).replace("Z", "+00:00"))
        heartbeat_age_seconds = max(0.0, (datetime.now(timezone.utc) - observed_at).total_seconds())
        if heartbeat_age_seconds > maximum_heartbeat_age_seconds:
            reasons.append("worker_heartbeat_stale")
    except (KeyError, TypeError, ValueError):
        reasons.append("worker_heartbeat_missing")
    status = "healthy" if not reasons else "degraded"
    return {
        "schema_version": "daily-research-data-health-v1",
        "status": status,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "expected_latest_trade_date": expected.isoformat(),
        "maximum_age_trading_days": maximum_age_trading_days,
        "coverage_generated_at": coverage.get("generated_at"),
        "coverage_ratio": coverage_ratio,
        "event_coverage_status": event_status,
        "required_price_cursor_count": len(required_pairs),
        "fresh_price_cursor_count": fresh,
        "missing_price_cursors": missing,
        "stale_price_cursors": stale,
        "invalid_price_cursor_dates": invalid_dates,
        "reasons": reasons,
        "warnings": warnings,
        "provider_counts": dict(sorted(Counter(str(value.get("provider", "unknown")) for value in cursors.values() if isinstance(value, dict)).items())),
        "worker_heartbeat": heartbeat or None,
        "worker_heartbeat_age_seconds": heartbeat_age_seconds,
        "maximum_heartbeat_age_seconds": maximum_heartbeat_age_seconds,
    }


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    args = parse_args()
    if args.maximum_age_trading_days < 0 or args.maximum_heartbeat_age_seconds < 0:
        raise SystemExit("maximum ages must be non-negative")
    as_of = args.as_of or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    health = build_health(
        _read_json(args.coverage), _read_json(args.cursor_store),
        as_of=as_of, maximum_age_trading_days=args.maximum_age_trading_days,
        worker_heartbeat=_read_json(args.worker_heartbeat),
        maximum_heartbeat_age_seconds=args.maximum_heartbeat_age_seconds,
    )
    _write_json(args.output, health)
    print(json.dumps(health, ensure_ascii=False))
    return 0 if health["status"] == "healthy" else 2


if __name__ == "__main__":
    raise SystemExit(main())
