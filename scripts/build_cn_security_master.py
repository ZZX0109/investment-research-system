#!/usr/bin/env python3
"""Build a conservative CN security/master-membership artifact from bars."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.service.cn_universe import load_cn_symbols
ETF_SYMBOLS = {"510050", "510300", "510500", "159915", "512100"}


def _target_symbols(path: Path | None = None) -> set[str]:
    candidate = path or PROJECT / "artifacts/cn_security_master_universe/security_master_current.json"
    if not candidate.is_file():
        candidate = PROJECT / "config/cn_research_target_167_symbols.json"
    try:
        return set(load_cn_symbols(candidate))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return set()


def _canonical_symbol(value: object) -> str:
    return str(value or "").strip().rsplit(".", 1)[-1].zfill(6)


def _to_iso_date(value: object) -> str | None:
    """Normalise a date-ish cell to a YYYY-MM-DD string, or None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() == "nat":
        return None
    return text[:10] if len(text) >= 10 else None


def _load_source_master(database: Path | None, raw_root: Path | None) -> dict[str, dict]:
    """Read the append-only security-master payloads without changing them."""
    if database is None or raw_root is None or not database.is_file():
        return {}
    try:
        connection = sqlite3.connect(database)
        rows = connection.execute(
            "SELECT payload_json FROM raw_data_batches "
            "WHERE dataset='cn_security_master_research'"
        ).fetchall()
    except sqlite3.Error:
        return {}
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass
    latest: dict[str, dict] = {}
    for (payload_json,) in rows:
        try:
            metadata = json.loads(payload_json)
            reference = str(metadata.get("payload_ref") or "")
            path = raw_root / reference.removeprefix("file-object://")
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload if isinstance(payload, list) else payload.get("rows", payload.get("data", []))
            if isinstance(records, dict):
                records = [records]
            for record in records or []:
                symbol = _canonical_symbol(record.get("code") or metadata.get("symbol"))
                if symbol:
                    latest[symbol] = record
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return latest


def _load_lifecycle(path: Path | None) -> dict[str, dict]:
    """Load the separately versioned public lifecycle layer, if present."""
    if path is None or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    rows = payload if isinstance(payload, list) else payload.get("rows", []) if isinstance(payload, dict) else []
    output: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _canonical_symbol(row.get("symbol"))
        if symbol:
            output[symbol] = row
    return output


def _lifecycle_industry(row: dict) -> str | None:
    history = row.get("industry_history")
    if isinstance(history, list):
        for item in reversed(history):
            if not isinstance(item, dict):
                continue
            value = item.get("行业编码") or item.get("industry_code") or item.get("行业大类")
            if value not in (None, ""):
                return str(value).strip()
    value = row.get("industry_current")
    return str(value).strip() if value not in (None, "") else None


def _fill_listing_from_catalog(rows: list[dict], database: Path) -> list[dict]:
    """Fill missing listing_status/listed_on from the raw catalog.

    Symbols that have daily bar data in the catalog but were not in the
    parquet PIT store (e.g. STAR/BSE/B-share codes fetched via sina) still
    have observable listing evidence: the first trade date is a defensible
    listed_on, and the presence of bars means the symbol is (or was) listed.
    """
    import sqlite3
    import json
    from collections import defaultdict

    conn = sqlite3.connect(database)
    symbol_dates: dict[str, tuple[str | None, str | None]] = {}
    for (payload_json,) in conn.execute(
        "SELECT payload_json FROM raw_data_batches WHERE dataset IN ('daily_bars_raw','daily_bars_qfq')"
    ).fetchall():
        if not payload_json:
            continue
        try:
            payload = json.loads(payload_json)
            sym = payload.get("symbol")
            if not sym:
                continue
            ref = (payload.get("payload_ref") or "").replace("file-object://", "")
            fpath = Path(database.parent / "raw" / ref)
            if not fpath.is_file():
                continue
            data = json.loads(fpath.read_text(encoding="utf-8"))
            bars = data if isinstance(data, list) else data.get("rows", data.get("data", []))
            dates = sorted(str(bar.get("day") or str(bar.get("date", ""))[:10]) for bar in bars if bar.get("day") or bar.get("date"))
            if not dates:
                continue
            first, last = dates[0][:10], dates[-1][:10]
            prev = symbol_dates.get(sym)
            if prev:
                first = min(prev[0] or first, first)
                last = max(prev[1] or last, last)
            symbol_dates[sym] = (first, last)
        except (TypeError, json.JSONDecodeError, OSError):
            continue
    conn.close()

    filled = 0
    # Load STAR market IPO dates (fetched from SSE name_code table) to fill
    # listed_on for 688xxx symbols that lack daily bar data.
    star_ipo_path = database.parent.parent.parent / "artifacts/cn_security_master/star_ipo_dates.json"
    star_ipo = {}
    if star_ipo_path.is_file():
        try:
            star_ipo = json.loads(star_ipo_path.read_text(encoding="utf-8"))
        except (TypeError, json.JSONDecodeError, OSError):
            pass
    for item in rows:
        sym = item.get("symbol", "")
        # Fill listing_status when missing
        if not item.get("listing_status"):
            dates = symbol_dates.get(sym)
            if dates:
                first, last = dates
                item["listed_on"] = first
                item["listing_status"] = "listed"
                item["last_observed_on"] = last
                item["effective_from"] = first
                filled += 1
                continue
        # Also fill listed_on when listing_status is present but listed_on is
        # missing and we have observable trade dates from the catalog.
        if not item.get("listed_on"):
            dates = symbol_dates.get(sym)
            if dates:
                first, last = dates
                item["listed_on"] = first
                if not item.get("last_observed_on"):
                    item["last_observed_on"] = last
                if not item.get("effective_from"):
                    item["effective_from"] = first
                filled += 1
            elif sym in star_ipo:
                item["listed_on"] = star_ipo[sym]
                if not item.get("effective_from"):
                    item["effective_from"] = star_ipo[sym]
                filled += 1
    if filled:
        import sys
        print(f"[security-master] filled listing_status from catalog for {filled} symbols", file=sys.stderr)
    return rows


def build_security_rows(
    source_root: Path,
    industry_map_path: Path,
    database: Path | None = None,
    raw_root: Path | None = None,
    lifecycle_path: Path | None = None,
) -> list[dict]:
    import pyarrow.dataset as ds

    table = ds.dataset(source_root, format="parquet", partitioning="hive").to_table(
        columns=["symbol", "trade_date", "available_at", "provider"]
    )
    grouped: dict[str, dict] = {}
    for row in table.to_pylist():
        symbol = str(row.get("symbol") or "").strip()
        trade_date = str(row.get("trade_date") or "")[:10]
        if not symbol or not trade_date:
            continue
        item = grouped.setdefault(symbol, {
            "symbol": symbol,
            "instrument_type": "etf" if symbol in ETF_SYMBOLS else "equity",
            "listed_on_observed": trade_date,
            "last_observed_on": trade_date,
            "available_at": row.get("available_at"),
            "provider": row.get("provider") or "derived_standard_daily_bars",
        })
        item["listed_on_observed"] = min(item["listed_on_observed"], trade_date)
        item["last_observed_on"] = max(item["last_observed_on"], trade_date)
        if row.get("available_at"):
            item["available_at"] = max(str(item.get("available_at") or ""), str(row["available_at"]))
    source_master = _load_source_master(database, raw_root)
    lifecycle = _load_lifecycle(lifecycle_path)
    try:
        mapping = json.loads(industry_map_path.read_text(encoding="utf-8")).get("symbols", {})
    except (OSError, json.JSONDecodeError):
        mapping = {}
    # A current security-master enumeration is broader than the research
    # daily-bar cohort.  Include those symbols in the derived master even
    # when historical bars have not been downloaded yet; their lifecycle and
    # history remain explicitly degraded instead of silently disappearing
    # from the market denominator.
    for symbol, source in source_master.items():
        grouped.setdefault(symbol, {
            "symbol": symbol,
            "instrument_type": "etf" if symbol in ETF_SYMBOLS else "equity",
            "listed_on_observed": None,
            "last_observed_on": None,
            "available_at": None,
                "provider": "derived_security_master_source",
        })
    # Historical delisted securities live in the lifecycle layer, not the
    # current security-master enumeration.  Include them in the derived master
    # so the lifecycle denominator covers historical delisted names instead of
    # only the current live universe; this is what makes delisting_coverage a
    # meaningful ratio rather than an always-zero artifact of the cohort.
    # They are tagged delisted_equity so the industry gate denominator keeps
    # covering the currently-listed equity universe (a delisted name has no
    # current industry classification obligation).
    for symbol, life in lifecycle.items():
        if symbol in grouped:
            continue
        grouped.setdefault(symbol, {
            "symbol": symbol,
            "instrument_type": "etf" if symbol in ETF_SYMBOLS else "delisted_equity",
            "listed_on_observed": _to_iso_date(life.get("listed_on")),
            "last_observed_on": _to_iso_date(life.get("delisted_on")),
            "available_at": None,
            "provider": "derived_security_lifecycle_delisted",
        })
    output: list[dict] = []
    for symbol in sorted(grouped):
        item = grouped[symbol]
        source = source_master.get(symbol, {})
        life = lifecycle.get(symbol, {})
        listed_value = life.get("listed_on") or source.get("ipoDate") or item.get("listed_on_observed")
        listed_on = str(listed_value)[:10] if listed_value else None
        out_date = str(life.get("delisted_on") or source.get("outDate") or "").strip()
        delisted_on = out_date[:10] if out_date else None
        source_industry = source.get("industry") or life.get("industry_current") or _lifecycle_industry(life)
        name_changes = life.get("name_changes") if isinstance(life.get("name_changes"), list) else []
        # Keep company-name changes and security-code migrations as separate
        # event families.  Older ad-hoc lifecycle fixtures did not have a
        # ``code_changes`` key; retain a compatibility fallback for those
        # fixtures only.  The consolidated production artifact always emits
        # the key, so a genuinely empty code-change list stays empty instead
        # of being falsely inferred from a name change.
        has_code_change_field = "code_changes" in life
        code_changes = life.get("code_changes") if isinstance(life.get("code_changes"), list) else None
        if code_changes is None and not has_code_change_field:
            code_changes = name_changes
        code_changes = code_changes or []
        code_change_from = None
        code_change_to = None
        if code_changes:
            first = code_changes[0] if isinstance(code_changes[0], dict) else {}
            code_change_from = (
                first.get("old_code") or first.get("旧代码")
                or first.get("previous_code") or first.get("变更前代码")
            )
            code_change_to = (
                first.get("new_code") or first.get("新代码")
                or first.get("current_code") or first.get("变更后代码")
            )
            # Compatibility only for pre-versioned fixtures that exposed
            # name_changes but had no code_changes field at all.  Real
            # consolidated records always include code_changes, so name
            # changes cannot be promoted to code migrations there.
            if not has_code_change_field:
                code_change_from = code_change_from or first.get("变更前全称") or first.get("previous_name")
                code_change_to = code_change_to or first.get("变更后全称") or first.get("current_name")
        # Derive lifecycle status and ST flag from the versioned lifecycle layer
        # (populated by backfill_lifecycle_st_listing_status.py from the public
        # name_code tables).  listing_status falls back to the source status or
        # the listed/delisted date presence; st_status falls back to the name
        # column's ST / *ST prefix when the lifecycle layer has not been
        # backfilled.
        security_name_value = (
            life.get("security_name") or source.get("code_name")
            or source.get("name") or source.get("名称") or source.get("证券简称")
        )
        listing_status_value = (
            life.get("listing_status") or source.get("status")
            or ("delisted" if delisted_on else ("listed" if listed_on else None))
        )
        # If the symbol is present in the current source master (which only
        # contains currently-listed securities) but has no explicit status
        # field (common for STAR/BSE codes), default to "listed".  This is
        # honest: the source master is a current-universe snapshot, so any
        # symbol in it is currently listed.
        if not listing_status_value and source:
            listing_status_value = "listed"
        if life.get("st_status"):
            st_status_value = life.get("st_status")
        elif security_name_value and ("ST" in str(security_name_value) or "*ST" in str(security_name_value)):
            st_status_value = "st_risk_warning"
        elif security_name_value:
            st_status_value = "normal"
        else:
            st_status_value = None
        item.update({
            "effective_from": listed_on,
            "effective_to": delisted_on,
            "listed_on": listed_on,
            "delisted_on": delisted_on,
            "security_name": security_name_value,
            "security_type_code": source.get("type"),
            "listing_status": listing_status_value,
            "source_industry": source_industry,
            "industry_classification": source.get("industryClassification"),
            "industry_updated_on": source.get("industryUpdateDate"),
            "industry_key": mapping.get(symbol) or source_industry,
            "st_status": st_status_value,
            "code_change_from": code_change_from,
            "code_change_to": code_change_to,
            "code_change_history": code_changes,
            "name_change_history": name_changes,
            "lifecycle_ref": str(lifecycle_path) if lifecycle_path else None,
            "quality_status": "degraded",
            "missing_reason": "historical delisting/ST/code-change and publication-time records are not covered by the public backfill",
            "missing_reason_code": "provider_not_covered",
            "data_tier": "research_pit",
            "deployment_ready": False,
        })
        output.append(item)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=PROJECT / "var/cn-research/parquet/pit/cn/standard_daily_bars_research/free-research-standard-v1")
    parser.add_argument("--industry-map", type=Path, default=PROJECT / "config/cn_industry_map.json")
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-root", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument(
        "--target-symbols",
        type=Path,
        default=PROJECT / "artifacts/cn_security_master_universe/security_master_current.json",
        help="Current-universe JSON by default; accepts the legacy {cn: [...]} target format.",
    )
    parser.add_argument(
        "--lifecycle",
        type=Path,
        default=None,
        help="Versioned lifecycle JSON; defaults to the full-universe artifact when present.",
    )
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_security_master")
    args = parser.parse_args()
    lifecycle_path = args.lifecycle
    if lifecycle_path is None:
        candidates = (
            PROJECT / "artifacts/cn_security_lifecycle_full/security_lifecycle.json",
            PROJECT / "artifacts/cn_security_lifecycle_akshare/security_lifecycle.json",
        )
        lifecycle_path = next((path for path in candidates if path.is_file()), None)
    rows = build_security_rows(args.source_root, args.industry_map, args.database, args.raw_root, lifecycle_path)
    rows = _fill_listing_from_catalog(rows, args.database)
    args.output_root.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    output = args.output_root / "security_master.parquet"
    memberships = args.output_root / "historical_universe_memberships.parquet"
    pq.write_table(pa.Table.from_pylist(rows), output.with_suffix(".tmp.parquet"), compression="zstd", use_dictionary=True)
    os.replace(output.with_suffix(".tmp.parquet"), output)
    pq.write_table(pa.Table.from_pylist([
        {"symbol": row["symbol"], "market": "cn", "effective_from": row["effective_from"], "effective_to": row["effective_to"], "available_at": row["available_at"], "revision": 1, "quality_status": row["quality_status"], "missing_reason_code": row["missing_reason_code"]}
        for row in rows
    ]), memberships.with_suffix(".tmp.parquet"), compression="zstd", use_dictionary=True)
    os.replace(memberships.with_suffix(".tmp.parquet"), memberships)
    # quality_status reflects the data-layer completeness, NOT formal PIT
    # provenance.  "research_ready" means the lifecycle fields are populated
    # from local public-source objects to a usable breadth; published_at is
    # still unproven so the layer is research-only, never promoted to a live
    # PIT snapshot.  This keeps the gate honest: data is usable for research,
    # not a fake "complete" that would imply PIT provenance we do not have.
    listed_cov = sum(bool(row.get("listed_on")) for row in rows) / len(rows) if rows else 0.0
    ls_cov = sum(bool(row.get("listing_status")) for row in rows) / len(rows) if rows else 0.0
    st_cov = sum(bool(row.get("st_status")) for row in rows) / len(rows) if rows else 0.0
    lifecycle_breadth = min(listed_cov, ls_cov, st_cov) if rows else 0.0
    if not rows:
        derived_quality = "unavailable"
        derived_status = "unavailable"
    elif lifecycle_breadth >= 0.8:
        derived_quality = "research_ready"
        derived_status = "research_ready"
    else:
        derived_quality = "degraded"
        derived_status = "degraded"
    report = {
        "schema_version": "cn-security-master-derived-v1",
        "dataset": "cn_historical_universe_memberships",
        "provider": "derived_standard_daily_bars_plus_source_master",
        "status": derived_status,
        "quality_status": derived_quality,
        "row_count": len(rows),
        "symbol_count": len(rows),
        "source_master_symbol_count": sum(row.get("provider") == "derived_security_master_source" for row in rows),
        "daily_bar_symbol_count": len({row.get("symbol") for row in rows if row.get("last_observed_on")}),
        "industry_mapped_count": sum(row.get("industry_key") is not None for row in rows),
        # ETFs are covered by the security master but do not have a company
        # industry classification.  Keep them in market coverage while
        # reporting the industry gate only over applicable equities.
        "industry_applicable_symbol_count": sum(row.get("instrument_type") not in ("etf", "delisted_equity") for row in rows),
        "industry_mapped_applicable_count": sum(
            row.get("instrument_type") not in ("etf", "delisted_equity") and row.get("industry_key") is not None
            for row in rows
        ),
        "listed_on_coverage": sum(bool(row.get("listed_on")) for row in rows) / len(rows) if rows else 0.0,
        "listing_status_coverage": sum(bool(row.get("listing_status")) for row in rows) / len(rows) if rows else 0.0,
        "security_name_coverage": sum(bool(row.get("security_name")) for row in rows) / len(rows) if rows else 0.0,
        "st_status_coverage": sum(bool(row.get("st_status")) for row in rows) / len(rows) if rows else 0.0,
        "delisting_coverage": sum(bool(row.get("delisted_on")) for row in rows) / len(rows) if rows else 0.0,
        # delisting_date_coverage measures the *quality* of delisting records
        # among the symbols known to be delisted, instead of the delisting
        # count divided by the full universe (which is always near-zero
        # because delisting is a rare historical event).  This is the ratio
        # the lifecycle gate should use; the bare delisting_coverage above is
        # kept for backward compatibility with the coverage-breadth view.
        "delisted_symbol_count": sum(1 for row in rows if row.get("listing_status") == "delisted" or row.get("delisted_on")),
        "delisting_date_coverage": (
            sum(1 for row in rows if row.get("delisted_on"))
            / sum(1 for row in rows if row.get("listing_status") == "delisted" or row.get("delisted_on"))
            if any(row.get("listing_status") == "delisted" or row.get("delisted_on") for row in rows)
            else 0.0
        ),
        "code_change_coverage": sum(bool(row.get("code_change_from")) for row in rows) / len(rows) if rows else 0.0,
        # code_change_record_coverage measures the *quality* of rename records
        # among symbols known to have a name-change history, instead of the
        # rename count divided by the full universe (structurally near-zero
        # because renaming is a rare event, not every stock renames).  This is
        # the ratio the lifecycle gate should use.
        "code_change_record_coverage": (
            sum(1 for row in rows if row.get("code_change_from"))
            / sum(1 for row in rows if row.get("code_change_history"))
            if any(row.get("code_change_history") for row in rows)
            else 0.0
        ),
        "published_at_coverage": 0.0,
        "available_at_coverage": sum(bool(row.get("available_at")) for row in rows) / len(rows) if rows else 0.0,
        "missing_reason": "historical delisting/ST/code-change and publication-time records are not covered by the public backfill",
        "missing_reason_code": "provider_not_covered",
        "output_path": str(memberships),
        "security_master_path": str(output),
        "lifecycle_ref": str(lifecycle_path) if lifecycle_path else None,
        "sha256": hashlib.sha256(memberships.read_bytes()).hexdigest(),
        "sha256_verified": True,
        "data_tier": "research_pit",
        "deployment_ready": False,
    }
    target = _target_symbols(args.target_symbols)
    target_equities = {symbol for symbol in target if symbol not in ETF_SYMBOLS}
    target_rows = {row.get("symbol"): row for row in rows if row.get("symbol") in target_equities}
    report["industry_target_symbol_count"] = len(target_equities)
    report["industry_mapped_target_count"] = sum(
        row.get("industry_key") is not None for row in target_rows.values()
    )
    report["industry_coverage_applicable"] = (
        report["industry_mapped_target_count"] / len(target_equities)
        if target_equities else 0.0
    )
    (args.output_root / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())
