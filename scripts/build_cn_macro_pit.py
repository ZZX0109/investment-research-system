#!/usr/bin/env python3
"""Normalize downloaded CN macro payloads into an explicit PIT audit artifact.

This command reads the append-only catalog/object store only.  Public macro
connectors currently expose observation dates but not a reliable release
timestamp, so records remain ``degraded`` and are never silently treated as
historically visible training features.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import re
import sqlite3
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
MACRO_DATASETS = {
    "cn_macro_cpi_monthly",
    "cn_macro_ppi_monthly",
    "cn_macro_pmi_monthly",
    "cn_macro_lpr",
    "cn_macro_shibor",
    "cn_macro_m2",
    "cn_macro_social_financing",
    "cn_macro_fx_rmb",
}


def _observation_period(row: dict) -> str | None:
    for key in ("日期", "TRADE_DATE", "trade_date", "date"):
        value = row.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
            except ValueError:
                return text[:10]
    value = row.get("月份")
    if value not in (None, ""):
        text = str(value).strip()
        match = re.search(r"(\d{4})[^0-9]?(\d{1,2})", text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-01"
        if re.fullmatch(r"\d{6}", text):
            return f"{text[:4]}-{text[4:]}-01"
    return None


def _source_release_date(dataset: str, row: dict) -> str | None:
    """CPI connector dates are economic-calendar release dates, without time."""
    if dataset != "cn_macro_cpi_monthly":
        return None
    value = row.get("日期")
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def build_report(database: Path, raw_root: Path, output_root: Path) -> dict:
    output_root.mkdir(parents=True, exist_ok=True)
    release_calendar = _load_release_calendar(PROJECT / "artifacts/cn_macro_release_calendar_nbs/nbs_release_calendar.json")
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT provider,dataset,available_at,payload_json "
            "FROM raw_data_batches WHERE dataset LIKE 'cn_macro_%'"
        ).fetchall()
    finally:
        connection.close()

    records: list[dict] = []
    datasets: dict[str, dict] = defaultdict(lambda: {
        "row_count": 0,
        "observation_count": 0,
        "published_at_count": 0,
        "source_release_date_count": 0,
        "planned_published_at_count": 0,
        "available_at_count": 0,
        "revision_count": 0,
        "periods": [],
        "malformed_count": 0,
    })
    for provider, dataset, catalog_available_at, payload_json in rows:
        if dataset not in MACRO_DATASETS:
            continue
        try:
            metadata = json.loads(payload_json)
            reference = str(metadata.get("payload_ref") or "")
            payload_path = raw_root / reference.removeprefix("file-object://")
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            datasets[dataset]["malformed_count"] += 1
            continue
        row_list = payload if isinstance(payload, list) else payload.get("rows", payload.get("data", []))
        if isinstance(row_list, dict):
            row_list = [row_list]
        if not isinstance(row_list, list):
            datasets[dataset]["malformed_count"] += 1
            continue
        for row in row_list:
            if not isinstance(row, dict):
                datasets[dataset]["malformed_count"] += 1
                continue
            source_release_date = _source_release_date(dataset, row)
            period = _observation_period(row)
            if dataset == "cn_macro_cpi_monthly" and source_release_date:
                release_day = datetime.fromisoformat(source_release_date).date()
                period = (release_day.replace(day=1) - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d")
            if period is None:
                datasets[dataset]["malformed_count"] += 1
                continue
            available_at = metadata.get("available_at") or catalog_available_at
            collected_at = metadata.get("fetched_at") or metadata.get("received_at") or available_at
            revision_id = str(metadata.get("revision_id") or metadata.get("revision") or metadata.get("payload_hash") or "")
            record = {
                "dataset": dataset,
                "series_id": dataset.removeprefix("cn_macro_"),
                "observation_period": period,
                "values": row,
                "published_at": None,
                "source_release_date": source_release_date,
                "source_release_date_semantics": "economic_calendar_release_date_without_time" if source_release_date else None,
                "planned_published_at": release_calendar.get((dataset, period), {}).get("planned_published_at"),
                "planned_release_source": release_calendar.get((dataset, period), {}).get("source_url"),
                "available_at": available_at,
                "revision_id": revision_id or None,
                "collected_at": collected_at,
                "provider": provider,
                "raw_hash": metadata.get("payload_hash"),
                "quality_status": "degraded",
                "missing_reason": "source publication/release time is not provided; collection time is not a PIT timestamp",
                "missing_reason_code": "published_time_unverified",
                "data_tier": "research_pit",
            }
            records.append(record)
            summary = datasets[dataset]
            summary["row_count"] += 1
            summary["observation_count"] += 1
            summary["available_at_count"] += int(bool(available_at))
            summary["revision_count"] += int(bool(revision_id))
            summary["source_release_date_count"] += int(bool(source_release_date))
            summary["planned_published_at_count"] += int(bool(record["planned_published_at"]))
            summary["periods"].append(period)

    records.sort(key=lambda item: (item["dataset"], item["observation_period"], item["revision_id"] or ""))
    records_path = output_root / "macro_pit.jsonl"
    with records_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    dataset_report: dict[str, dict] = {}
    for dataset in sorted(MACRO_DATASETS):
        item = datasets[dataset]
        periods = sorted(item.pop("periods"))
        item.update({
            "status": "degraded" if item["row_count"] else "unavailable",
            "quality_status": "degraded" if item["row_count"] else "unavailable",
            "published_at_coverage": 0.0,
            "source_release_date_coverage": item["source_release_date_count"] / item["row_count"] if item["row_count"] else 0.0,
            "planned_published_at_coverage": item["planned_published_at_count"] / item["row_count"] if item["row_count"] else 0.0,
            "available_at_coverage": item["available_at_count"] / item["row_count"] if item["row_count"] else 0.0,
            "revision_coverage": item["revision_count"] / item["row_count"] if item["row_count"] else 0.0,
            "date_start": periods[0] if periods else None,
            "date_end": periods[-1] if periods else None,
            "missing_reason": "source publication/release time is not provided",
            "missing_reason_code": "published_time_unverified",
        })
        dataset_report[dataset] = item
    report = {
        "schema_version": "cn-macro-pit-audit-v1",
        "dataset": "cn_macro_pit",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "degraded" if records else "unavailable",
        "quality_status": "degraded" if records else "unavailable",
        "deployment_ready": False,
        "data_tier": "research_pit",
        "record_count": len(records),
        "published_at_coverage": 0.0,
        "source_release_date_coverage": sum(bool(item.get("source_release_date")) for item in records) / len(records) if records else 0.0,
        "planned_published_at_coverage": sum(bool(item.get("planned_published_at")) for item in records) / len(records) if records else 0.0,
        "available_at_coverage": sum(bool(item.get("available_at")) for item in records) / len(records) if records else 0.0,
        "revision_coverage": sum(bool(item.get("revision_id")) for item in records) / len(records) if records else 0.0,
        "missing_reason": "source publication/release time is not provided; macro features must remain blocked for PIT training",
        "missing_reason_code": "published_time_unverified",
        "output_path": str(records_path),
        "datasets": dataset_report,
    }
    (output_root / "macro_pit_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _load_release_calendar(path: Path) -> dict[tuple[str, str], dict]:
    if not path.is_file():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    dataset_map = {
        "cpi_monthly": "cn_macro_cpi_monthly",
        "ppi_monthly": "cn_macro_ppi_monthly",
        "pmi_monthly": "cn_macro_pmi_monthly",
    }
    return {
        (dataset_map.get(row.get("series"), ""), _period_key(row.get("data_period"))): row
        for row in rows
        if row.get("series") in dataset_map and row.get("data_period")
    }


def _period_key(value: object) -> str:
    text = str(value)
    return f"{text[:7]}-01" if len(text) >= 7 else text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--raw-root", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_research_auxiliary")
    args = parser.parse_args()
    report = build_report(args.database, args.raw_root, args.output_root)
    print(json.dumps({"status": report["status"], "record_count": report["record_count"], "published_at_coverage": report["published_at_coverage"]}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
