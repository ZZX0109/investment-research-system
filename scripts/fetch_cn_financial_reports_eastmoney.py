#!/usr/bin/env python3
"""Land all-market Eastmoney quarterly financial reports with provenance.

The per-security Sina abstract endpoint is useful for extended ratios but is
too slow to provide a timely full-market core-data backfill.  Eastmoney's
public report endpoints are paged by report period.  The ``performance``
family supplies EPS, revenue, parent net profit, ROE and YoY fields; the
``income``, ``cashflow`` and ``balance`` families supply the three statements.
This collector keeps each provider payload immutable in a landing run and
writes a small normalized record stream for reconciliation with the
authoritative CNINFO disclosure evidence.

``NOTICE_DATE`` is provider evidence, not a substitute for an official first
publication/revision chain.  Consequently this output is explicitly
research-only and must not be promoted to a formal PIT snapshot by itself.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable
from uuid import uuid4

import requests


PROJECT = Path(__file__).resolve().parents[1]
URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
SCHEMA_VERSION = "cn-financial-reports-eastmoney-v1"
REPORT_FAMILIES: dict[str, dict[str, Any]] = {
    "performance": {
        "report_name": "RPT_LICO_FN_CPD", "period_key": "REPORTDATE",
        "sort_columns": "UPDATE_DATE,SECURITY_CODE", "sort_types": "-1,-1",
        "filter": "(REPORTDATE='{date}')",
        "fields": ("BASIC_EPS", "TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT", "WEIGHTAVG_ROE", "YSTZ", "SJLTZ", "MGJYXJJE", "XSMLL"),
    },
    "income": {
        "report_name": "RPT_DMSK_FN_INCOME", "period_key": "REPORT_DATE",
        "sort_columns": "NOTICE_DATE,SECURITY_CODE", "sort_types": "-1,-1",
        "filter": "(SECURITY_TYPE_CODE in (\"058001001\",\"058001008\"))(TRADE_MARKET_CODE!=\"069001017\")(REPORT_DATE='{date}')",
        "fields": ("PARENT_NETPROFIT", "DEDUCT_PARENT_NETPROFIT", "TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "OPERATE_COST", "TOTAL_OPERATE_COST", "OPERATE_PROFIT", "TOTAL_PROFIT", "SALE_EXPENSE", "MANAGE_EXPENSE", "FINANCE_EXPENSE", "INCOME_TAX"),
    },
    "cashflow": {
        "report_name": "RPT_DMSK_FN_CASHFLOW", "period_key": "REPORT_DATE",
        "sort_columns": "NOTICE_DATE,SECURITY_CODE", "sort_types": "-1,-1",
        "filter": "(SECURITY_TYPE_CODE in (\"058001001\",\"058001008\"))(TRADE_MARKET_CODE!=\"069001017\")(REPORT_DATE='{date}')",
        "fields": ("NETCASH_OPERATE", "NETCASH_INVEST", "NETCASH_FINANCE", "END_CCE", "BEGIN_CCE", "SALES_SERVICES", "PAY_STAFF_CASH", "CONSTRUCT_LONG_ASSET"),
    },
    "balance": {
        "report_name": "RPT_DMSK_FN_BALANCE", "period_key": "REPORT_DATE",
        "sort_columns": "NOTICE_DATE,SECURITY_CODE", "sort_types": "-1,-1",
        "filter": "(SECURITY_TYPE_CODE in (\"058001001\",\"058001008\"))(TRADE_MARKET_CODE!=\"069001017\")(REPORT_DATE='{date}')",
        "fields": ("TOTAL_ASSETS", "TOTAL_LIABILITIES", "TOTAL_EQUITY", "MONETARYFUNDS", "ACCOUNTS_RECE", "INVENTORY", "ACCOUNTS_PAYABLE", "CURRENT_RATIO", "DEBT_ASSET_RATIO", "SHORT_LOAN"),
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Land all-market Eastmoney quarterly financial reports")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts" / "cn_financial_reports_eastmoney")
    parser.add_argument("--start-year", type=int, default=2010)
    parser.add_argument("--end-period", default=None, help="YYYYMMDD; defaults to the latest fully disclosed quarter")
    parser.add_argument("--run-id", default=None, help="immutable landing run identity; defaults to the requested period range")
    parser.add_argument("--report-family", choices=tuple(REPORT_FAMILIES), default="performance")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--request-interval-seconds", type=float, default=0.2)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.start_year < 2010 or args.page_size <= 0 or args.request_interval_seconds < 0 or args.retries <= 0:
        raise SystemExit("invalid collector arguments")
    end_period = args.end_period or _latest_fully_disclosed_period(date.today())
    periods = _report_periods(args.start_year, end_period)
    if not periods:
        raise SystemExit("no report periods requested")
    family = args.report_family
    run_id = args.run_id or f"eastmoney-{family}-{periods[0]}-{periods[-1]}"
    run_root = args.output_root / "landing" / run_id
    progress_path = run_root / "manifest.json"
    manifest = _load_manifest(progress_path, run_id, periods, family)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 research-data-collector/1.0", "Accept": "application/json"})
    try:
        for index, period in enumerate(periods, start=1):
            _collect_period(args, session, run_root, manifest, progress_path, period)
            print(f"period {index}/{len(periods)} {period} {manifest['periods'][period]['status']}", flush=True)
    finally:
        session.close()

    completed = [state for state in manifest["periods"].values() if state.get("status") == "complete"]
    report = {
        "schema_version": SCHEMA_VERSION,
        "data_tier": "research_pit",
        "research_only": True,
        "deployment_ready": False,
        "provider": "eastmoney_datacenter",
        "dataset": f"quarterly_{family}_reports",
        "report_family": family,
        "run_id": run_id,
        "landing_manifest": str(progress_path.relative_to(PROJECT)),
        "target_period_count": len(periods),
        "completed_period_count": len(completed),
        "row_count": sum(int(state.get("record_count", 0)) for state in completed),
        "published_at_coverage": _weighted_coverage(completed, "published_at_count"),
        "status": "complete" if len(completed) == len(periods) else "partial",
        "missing_reason_code": "official_publication_and_revision_reconciliation_required",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest["status"] = "complete" if len(completed) == len(periods) else "partial"
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write(progress_path, manifest)
    _atomic_write(args.output_root / f"{family}-latest.json", report)
    if family == "performance":
        _atomic_write(args.output_root / "latest.json", report)
    print(json.dumps({key: report[key] for key in ("status", "completed_period_count", "row_count", "published_at_coverage")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 1


def _collect_period(
    args: argparse.Namespace,
    session: requests.Session,
    run_root: Path,
    manifest: dict[str, Any],
    manifest_path: Path,
    period: str,
) -> None:
    state = manifest["periods"].setdefault(period, _empty_period_state())
    if state.get("status") == "complete":
        return
    first = _request_page(args, session, period, 1)
    result = _result(first)
    pages = int(result.get("pages") or 0)
    if pages <= 0:
        raise RuntimeError(f"eastmoney_pages_invalid:{period}")
    state["expected_pages"] = pages
    state["status"] = "partial"
    _atomic_write(manifest_path, manifest)
    for page in range(1, pages + 1):
        page_path = run_root / period / f"page-{page:04d}.json"
        if page_path.exists():
            envelope = _read_json(page_path)
        else:
            payload = first if page == 1 else _request_page(args, session, period, page)
            envelope = _envelope(period, page, payload, args.report_family)
            _atomic_write(page_path, envelope)
        records = _result(envelope.get("payload")).get("data") or []
        if not isinstance(records, list):
            raise RuntimeError(f"eastmoney_records_invalid:{period}:{page}")
        state["completed_pages"] = max(int(state.get("completed_pages", 0)), page)
        state["record_count"] = int(state.get("record_count", 0)) + len(records) if page > int(state.get("counted_pages", 0)) else int(state.get("record_count", 0))
        state["published_at_count"] = int(state.get("published_at_count", 0)) + sum(bool(_normalize_record(row, args.report_family).get("published_at")) for row in records) if page > int(state.get("counted_pages", 0)) else int(state.get("published_at_count", 0))
        state["counted_pages"] = max(int(state.get("counted_pages", 0)), page)
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        _atomic_write(manifest_path, manifest)
        if page < pages:
            time.sleep(args.request_interval_seconds)
    state["status"] = "complete"
    state["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["updated_at"] = state["completed_at"]
    _atomic_write(manifest_path, manifest)


def _request_page(args: argparse.Namespace, session: requests.Session, period: str, page: int) -> dict[str, Any]:
    family = REPORT_FAMILIES[args.report_family]
    observation = f"{period[:4]}-{period[4:6]}-{period[6:]}"
    params = {
        "sortColumns": family["sort_columns"],
        "sortTypes": family["sort_types"],
        "pageSize": str(args.page_size),
        "pageNumber": str(page),
        "reportName": family["report_name"],
        "columns": "ALL",
        "filter": family["filter"].format(date=observation),
    }
    last: Exception | None = None
    for attempt in range(args.retries):
        try:
            response = session.get(URL, params=params, timeout=args.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
            if not _result(payload):
                raise RuntimeError("eastmoney_result_missing")
            return payload
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last = exc
            if attempt + 1 < args.retries:
                time.sleep(max(args.request_interval_seconds, 1.0 * (2 ** attempt)))
    raise RuntimeError(f"eastmoney_request_failed:{period}:{page}:{type(last).__name__}:{last}")


def _envelope(period: str, page: int, payload: dict[str, Any], report_family: str = "performance") -> dict[str, Any]:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset": f"quarterly_{report_family}_reports",
        "report_family": report_family,
        "provider": "eastmoney_datacenter",
        "source_uri": URL,
        "report_period": period,
        "page": page,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw_payload_sha256": hashlib.sha256(raw).hexdigest(),
        "payload": payload,
        "normalized_records": [_normalize_record(row, report_family) for row in _result(payload).get("data") or []],
    }


def _normalize_record(row: Any, report_family: str = "performance") -> dict[str, Any]:
    source = row if isinstance(row, dict) else {}
    family = REPORT_FAMILIES[report_family]
    code = str(source.get("SECURITY_CODE") or "").zfill(6)
    return {
        "symbol": code or None,
        "report_period": _date_only(source.get(family["period_key"])),
        "published_at": _date_only(source.get("NOTICE_DATE")),
        "provider_updated_at": _date_only(source.get("UPDATE_DATE")),
        "source_provider": "eastmoney_datacenter",
        "source_uri": URL,
        "report_family": report_family,
        "metrics": {key: source.get(key) for key in family["fields"]},
    }


def _report_periods(start_year: int, end_period: str) -> list[str]:
    if len(end_period) != 8 or not end_period.isdigit():
        raise ValueError("end period must be YYYYMMDD")
    allowed = ("0331", "0630", "0930", "1231")
    return [f"{year}{suffix}" for year in range(start_year, int(end_period[:4]) + 1) for suffix in allowed if f"{year}{suffix}" <= end_period]


def _latest_fully_disclosed_period(today: date) -> str:
    # Statutory disclosure cut-offs: Q1 Apr-30, H1 Aug-31, Q3 Oct-31,
    # annual Apr-30 of the following year.  Stop at the last fully due period.
    year = today.year
    if today <= date(year, 4, 30):
        return f"{year - 1}1231"
    if today <= date(year, 8, 31):
        return f"{year}0331"
    if today <= date(year, 10, 31):
        return f"{year}0630"
    return f"{year}0930"


def _load_manifest(path: Path, run_id: str, periods: Iterable[str], report_family: str = "performance") -> dict[str, Any]:
    if path.exists():
        payload = _read_json(path)
        if (
            payload.get("run_id") == run_id
            and payload.get("schema_version") == SCHEMA_VERSION
            and payload.get("report_family", "performance") == report_family
        ):
            return payload
        raise RuntimeError(f"landing_manifest_identity_mismatch:{path}")
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "provider": "eastmoney_datacenter",
        "report_family": report_family,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "periods": {period: _empty_period_state() for period in periods},
    }


def _empty_period_state() -> dict[str, Any]:
    return {"status": "pending", "expected_pages": 0, "completed_pages": 0, "counted_pages": 0, "record_count": 0, "published_at_count": 0}


def _result(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    value = payload.get("result")
    return value if isinstance(value, dict) else {}


def _date_only(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def _weighted_coverage(states: list[dict[str, Any]], key: str) -> float:
    total = sum(int(state.get("record_count", 0)) for state in states)
    return sum(int(state.get(key, 0)) for state in states) / total if total else 0.0


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"json_object_expected:{path}")
    return payload


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
