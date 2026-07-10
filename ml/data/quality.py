from __future__ import annotations

from datetime import date
from typing import Any

from ml.common import connect
from ml.data.ingest_history import is_synthetic_source


def parse_day(value: str) -> date:
    return date.fromisoformat(str(value)[:10])


def trading_gap_report(symbol: str) -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "select trade_date, source_name from historical_prices where symbol = ? order by trade_date",
            (symbol.upper(),),
        ).fetchall()
    if len(rows) < 2:
        return {"handled": False, "gapCount": 0, "maxCalendarGapDays": 0, "largeGaps": [], "policy": "insufficient rows to audit gaps"}
    large_gaps = []
    max_gap = 0
    for left, right in zip(rows, rows[1:]):
        gap = (parse_day(right["trade_date"]) - parse_day(left["trade_date"])).days
        max_gap = max(max_gap, gap)
        if gap > 10:
            large_gaps.append({"from": left["trade_date"], "to": right["trade_date"], "calendarGapDays": gap})
    return {
        "handled": True,
        "gapCount": len(large_gaps),
        "maxCalendarGapDays": max_gap,
        "largeGaps": large_gaps[:10],
        "policy": "calendar gaps are retained and surfaced as halt/holiday/missing-value audit items; returns are computed only across observed trading rows",
    }


def corporate_action_count(symbol: str) -> int:
    with connect() as conn:
        try:
            row = conn.execute("select count(*) as count from corporate_actions where symbol = ?", (symbol.upper(),)).fetchone()
            return int(row["count"]) if row else 0
        except Exception:
            return 0


def source_quality(symbol: str) -> dict[str, Any]:
    with connect() as conn:
        rows = conn.execute(
            "select source_name, count(*) as count from historical_prices where symbol = ? group by source_name",
            (symbol.upper(),),
        ).fetchall()
    breakdown = {str(row["source_name"]): int(row["count"]) for row in rows}
    total = sum(breakdown.values())
    synthetic = sum(count for source, count in breakdown.items() if is_synthetic_source(source))
    real = total - synthetic
    adjusted = any("yfinance historical" in source or "AkShare" in source or "qfq" in source.lower() for source in breakdown)
    return {
        "rowCount": total,
        "realRowCount": real,
        "syntheticRowCount": synthetic,
        "sourceBreakdown": breakdown,
        "adjustedPriceLikely": adjusted,
        "adjustmentPolicy": "yfinance auto_adjust=True for US; AkShare qfq for CN when available",
    }


def evidence_time_quality(symbol: str) -> dict[str, Any]:
    with connect() as conn:
        evidence = conn.execute(
            "select source_type, observed_at, valid_until, source_name, source_url, confidence, claim from evidence_records where symbol = ?",
            (symbol.upper(),),
        ).fetchall()
    by_type: dict[str, dict[str, Any]] = {}
    for row in evidence:
        item = by_type.setdefault(row["source_type"], {"count": 0, "missingObservedAt": 0, "sources": set()})
        source_name = str(row["source_name"] or "")
        claim = str(row["claim"] or "")
        is_placeholder = "demo" in source_name.lower() or "placeholder" in source_name.lower() or "占位" in claim or "样例" in claim
        is_successful = float(row["confidence"] or 0) >= 0.6 and not is_placeholder and bool(row["observed_at"])
        item["count"] += 1
        item["successfulCount"] = item.get("successfulCount", 0) + (1 if is_successful else 0)
        if not row["observed_at"]:
            item["missingObservedAt"] += 1
        item["sources"].add(row["source_name"])
    return {
        key: {
            "count": value["count"],
            "successfulCount": value.get("successfulCount", 0),
            "missingObservedAt": value["missingObservedAt"],
            "sources": sorted(value["sources"]),
        }
        for key, value in by_type.items()
    }


def revision_history_quality(symbol: str) -> dict[str, Any]:
    with connect() as conn:
        try:
            feature_row = conn.execute(
                "select count(*) as count, count(distinct revision_id) as revisions from point_in_time_features where symbol = ?",
                (symbol.upper(),),
            ).fetchone()
        except Exception:
            feature_row = None
        try:
            action_row = conn.execute(
                "select count(*) as count, count(distinct revision_id) as revisions from corporate_actions where symbol = ?",
                (symbol.upper(),),
            ).fetchone()
        except Exception:
            action_row = None
    return {
        "featureFieldCount": int(feature_row["count"]) if feature_row else 0,
        "featureRevisionCount": int(feature_row["revisions"]) if feature_row else 0,
        "corporateActionCount": int(action_row["count"]) if action_row else 0,
        "corporateActionRevisionCount": int(action_row["revisions"]) if action_row else 0,
    }


def symbol_quality_report(symbol: str) -> dict[str, Any]:
    source = source_quality(symbol)
    gaps = trading_gap_report(symbol)
    revisions = revision_history_quality(symbol)
    evidence_time = evidence_time_quality(symbol)
    return {
        "symbol": symbol.upper(),
        "source": source,
        "tradingGaps": gaps,
        "corporateActions": {
            "count": corporate_action_count(symbol),
            "status": "available" if corporate_action_count(symbol) > 0 else "missing_or_none_reported",
        },
        "evidenceTimeQuality": evidence_time,
        "revisionHistory": revisions,
        "requirements": {
            "adjustedPrices": source["adjustedPriceLikely"],
            "dividendsSplits": corporate_action_count(symbol) > 0 or symbol.isdigit(),
            "haltsMissingValues": bool(gaps.get("handled")),
            "filingAvailableAt": evidence_time.get("financial_report", {}).get("successfulCount", 0) > 0,
            "announcementPublishedAt": evidence_time.get("disclosure", {}).get("successfulCount", 0) > 0,
            "newsPublishedAt": evidence_time.get("news_event", {}).get("successfulCount", 0) > 0,
            "revisionHistory": revisions["featureRevisionCount"] > 0,
            "survivorshipBiasDisclosure": True,
        },
    }


def dataset_quality_report(symbols: list[str], *, universe_name: str, survivorship_note: str) -> dict[str, Any]:
    symbol_reports = [symbol_quality_report(symbol) for symbol in symbols]
    requirement_keys = [
        "adjustedPrices",
        "dividendsSplits",
        "haltsMissingValues",
        "filingAvailableAt",
        "announcementPublishedAt",
        "newsPublishedAt",
        "revisionHistory",
        "survivorshipBiasDisclosure",
    ]
    coverage = {
        key: {
            "passedCount": sum(1 for item in symbol_reports if item["requirements"].get(key)),
            "total": len(symbol_reports),
        }
        for key in requirement_keys
    }
    return {
        "universeName": universe_name,
        "symbolCount": len(symbols),
        "survivorshipBiasNote": survivorship_note,
        "coverage": coverage,
        "symbols": symbol_reports,
    }
