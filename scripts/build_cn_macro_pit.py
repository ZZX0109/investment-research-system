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
    actual_releases = _load_actual_releases(PROJECT / "artifacts/cn_macro_actual_release_nbs/actual_releases.json")
    # The public macro collectors contain observation dates, while the
    # research retry pass collected additional official publication evidence
    # from PBC/CFETS.  Merge that evidence here without promoting unresolved
    # or date-only rows: the resulting record keeps its evidence level and
    # timestamp precision so downstream PIT gates can distinguish direct
    # timestamps from rule-derived timestamps.
    publication_evidence = _load_publication_evidence(
        PROJECT / "artifacts/subagent_macro_history_retry/normalized/release_date_mapping.jsonl"
    )
    connection = sqlite3.connect(database)
    try:
        rows = connection.execute(
            "SELECT provider,dataset,available_at,payload_json "
            "FROM raw_data_batches WHERE dataset LIKE 'cn_macro_%'"
        ).fetchall()
    finally:
        connection.close()

    records: list[dict] = []
    evidence_levels: dict[str, int] = defaultdict(int)
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
            actual = actual_releases.get((dataset, period), {})
            evidence = publication_evidence.get((dataset, _evidence_period_key(dataset, period)), {})
            # An NBS article can be discovered successfully while its page
            # lacks an explicit publication timestamp.  That unresolved
            # discovery must not shadow a verified timestamp from the
            # source-specific retry mapping; otherwise refreshing the NBS
            # collector would silently reduce historical PIT coverage.
            publication = actual if actual.get("published_at") else evidence if evidence.get("published_at") else actual or evidence
            published_at = publication.get("published_at")
            record = {
                "dataset": dataset,
                "series_id": dataset.removeprefix("cn_macro_"),
                "observation_period": period,
                "values": row,
                "published_at": published_at,
                "published_at_semantics": (
                    "official_article_pubdate"
                    if actual.get("published_at")
                    else evidence.get("evidence_subtype")
                    if published_at
                    else None
                ),
                "publication_evidence_level": publication.get("evidence_level") or (
                    "actual" if actual.get("published_at") else None
                ),
                "publication_timestamp_precision": publication.get("timestamp_precision"),
                "publication_source_ref": publication.get("source_ref") or actual.get("source_url"),
                "publication_source_url": publication.get("source_url"),
                "source_release_date": source_release_date,
                "source_release_date_semantics": "economic_calendar_release_date_without_time" if source_release_date else None,
                "planned_published_at": release_calendar.get((dataset, period), {}).get("planned_published_at"),
                "planned_release_source": release_calendar.get((dataset, period), {}).get("source_url"),
                "available_at": published_at or available_at,
                "revision_id": revision_id or None,
                "collected_at": collected_at,
                "provider": provider,
                "raw_hash": metadata.get("payload_hash"),
                "quality_status": "complete" if published_at else "degraded",
                "missing_reason": None if published_at else "source publication/release time is not provided; collection time is not a PIT timestamp",
                "missing_reason_code": None if published_at else "published_time_unverified",
                "data_tier": "research_pit",
            }
            records.append(record)
            evidence_levels[str(record.get("publication_evidence_level") or "unresolved")] += 1
            summary = datasets[dataset]
            summary["row_count"] += 1
            summary["observation_count"] += 1
            summary["published_at_count"] += int(bool(published_at))
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
            "status": "complete" if item["row_count"] and item["published_at_count"] == item["row_count"] else "degraded" if item["row_count"] else "unavailable",
            "quality_status": "complete" if item["row_count"] and item["published_at_count"] == item["row_count"] else "degraded" if item["row_count"] else "unavailable",
            "published_at_coverage": item["published_at_count"] / item["row_count"] if item["row_count"] else 0.0,
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
        "status": "complete" if records and all(item.get("published_at") for item in records) else "degraded" if records else "unavailable",
        "quality_status": "complete" if records and all(item.get("published_at") for item in records) else "degraded" if records else "unavailable",
        "deployment_ready": False,
        "data_tier": "research_pit",
        "record_count": len(records),
        "published_at_coverage": sum(bool(item.get("published_at")) for item in records) / len(records) if records else 0.0,
        "source_release_date_coverage": sum(bool(item.get("source_release_date")) for item in records) / len(records) if records else 0.0,
        "planned_published_at_coverage": sum(bool(item.get("planned_published_at")) for item in records) / len(records) if records else 0.0,
        "available_at_coverage": sum(bool(item.get("available_at")) for item in records) / len(records) if records else 0.0,
        "revision_coverage": sum(bool(item.get("revision_id")) for item in records) / len(records) if records else 0.0,
        "evidence_levels": dict(sorted(evidence_levels.items())),
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


def _load_actual_releases(path: Path) -> dict[tuple[str, str], dict]:
    if not path.is_file():
        return {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        (
            f"cn_macro_{str(row.get('series') or '')}",
            _period_key(row.get("observation_period")),
        ): row
        for row in rows
        if isinstance(row, dict) and row.get("series") and row.get("observation_period")
    }


def _evidence_period_key(dataset: str, value: object) -> str:
    """Normalize a mapping period to the same key used by the raw record.

    M2 and social-financing records are monthly observations represented as
    ``YYYY-MM-01`` by this builder.  LPR, SHIBOR and FX records are daily and
    must retain their exact day; collapsing them to a month would incorrectly
    apply one publication timestamp to every observation in that month.
    """
    text = str(value or "")
    if dataset in {"cn_macro_m2", "cn_macro_social_financing"}:
        return _period_key(text)
    return text[:10]


def _load_publication_evidence(path: Path) -> dict[tuple[str, str], dict]:
    """Load only mapped official evidence from the research retry artifact.

    ``date_level`` rows deliberately remain in the index with no
    ``published_at`` so the caller can preserve an explicit unresolved PIT
    state.  Duplicate rows are resolved deterministically by preferring an
    actual timestamp over an unresolved mapping and then the first source
    record, which keeps the raw evidence hash stable across runs.
    """
    if not path.is_file():
        return {}
    evidence: dict[tuple[str, str], dict] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for line in lines:
        try:
            item = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(item, dict) or item.get("status") != "mapped":
            continue
        dataset = str(item.get("baseline_dataset") or "")
        if dataset not in MACRO_DATASETS:
            continue
        period = _evidence_period_key(dataset, item.get("observation_period"))
        if not period:
            continue
        key = (dataset, period)
        current = evidence.get(key)
        current_rank = 1 if current and current.get("published_at") else 0
        item_rank = 1 if item.get("published_at") else 0
        if current is None or item_rank > current_rank:
            evidence[key] = item
    return evidence


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
