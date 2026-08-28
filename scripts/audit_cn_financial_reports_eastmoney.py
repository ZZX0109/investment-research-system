#!/usr/bin/env python3
"""Audit immutable Eastmoney financial-report landing runs without mutating them.

The collector's manifest is only a progress ledger.  This verifier checks the
landing-page hash, family/period identity, schema shape, security codes and
provider publication-date coverage before the data can move to a research
reconciliation layer.  It deliberately does not assert formal PIT validity:
that still requires CNINFO first-publication and revision reconciliation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "cn-financial-reports-eastmoney-audit-v1"
_SYMBOL = re.compile(r"^\d{6}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts" / "cn_financial_reports_eastmoney")
    parser.add_argument("--report-family", choices=("performance", "income", "cashflow", "balance"), default="performance")
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = audit(args.output_root, args.report_family)
    output = args.output or args.output_root / f"{args.report_family}-audit.json"
    _atomic_write(output, report)
    print(json.dumps({key: report[key] for key in ("status", "completed_period_count", "record_count", "invalid_page_count", "published_at_coverage")}, ensure_ascii=False))
    return 0 if report["status"] == "complete" else 2


def audit(output_root: Path, report_family: str) -> dict[str, Any]:
    manifest_path = _find_manifest(output_root, report_family)
    if manifest_path is None:
        return _report(report_family, status="unavailable", blocking=["landing_manifest_missing"])
    try:
        manifest = _read_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return _report(report_family, status="blocked", blocking=["landing_manifest_unreadable"])
    periods = manifest.get("periods")
    if not isinstance(periods, dict):
        return _report(report_family, status="blocked", blocking=["landing_manifest_periods_invalid"], manifest_path=manifest_path)

    completed = 0
    record_count = 0
    published_count = 0
    page_count = 0
    invalid_pages: list[dict[str, str]] = []
    incomplete_periods: list[str] = []
    for period, state in sorted(periods.items()):
        if not isinstance(state, dict) or state.get("status") != "complete":
            incomplete_periods.append(str(period))
            continue
        completed += 1
        expected = int(state.get("expected_pages", 0) or 0)
        if expected <= 0:
            invalid_pages.append({"period": str(period), "page": "manifest", "reason": "expected_pages_missing"})
            continue
        for page in range(1, expected + 1):
            page_count += 1
            path = manifest_path.parent / str(period) / f"page-{page:04d}.json"
            problem, rows = _verify_page(path, str(period), report_family)
            if problem:
                invalid_pages.append({"period": str(period), "page": str(page), "reason": problem})
                continue
            record_count += len(rows)
            published_count += sum(bool(row.get("published_at")) for row in rows)
    total_periods = len(periods)
    coverage = published_count / record_count if record_count else 0.0
    is_complete = bool(total_periods and completed == total_periods and not invalid_pages and not incomplete_periods)
    return {
        "schema_version": SCHEMA_VERSION,
        "provider": "eastmoney_datacenter",
        "report_family": report_family,
        "landing_manifest": str(manifest_path.relative_to(PROJECT)) if manifest_path.is_relative_to(PROJECT) else str(manifest_path),
        "run_id": manifest.get("run_id"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if is_complete else "partial",
        "research_only": True,
        "formal_pit_verified": False,
        "target_period_count": total_periods,
        "completed_period_count": completed,
        "page_count": page_count,
        "record_count": record_count,
        "published_at_count": published_count,
        "published_at_coverage": coverage,
        "invalid_page_count": len(invalid_pages),
        "invalid_pages": invalid_pages[:100],
        "incomplete_periods": incomplete_periods,
        "blocking_reasons": (
            (["financial_landing_download_incomplete"] if incomplete_periods else [])
            + (["financial_landing_integrity_failed"] if invalid_pages else [])
            + ["official_publication_and_revision_reconciliation_required"]
        ),
    }


def _verify_page(path: Path, period: str, report_family: str) -> tuple[str | None, list[dict[str, Any]]]:
    try:
        envelope = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return "page_unreadable", []
    if envelope.get("report_family", "performance") != report_family:
        return "report_family_mismatch", []
    if str(envelope.get("report_period")) != period:
        return "report_period_mismatch", []
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return "payload_missing", []
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if envelope.get("raw_payload_sha256") != hashlib.sha256(raw).hexdigest():
        return "raw_payload_hash_mismatch", []
    rows = envelope.get("normalized_records")
    if not isinstance(rows, list):
        return "normalized_records_missing", []
    for row in rows:
        if not isinstance(row, dict) or not _SYMBOL.fullmatch(str(row.get("symbol") or "")):
            return "normalized_symbol_invalid", []
        if row.get("report_period") != f"{period[:4]}-{period[4:6]}-{period[6:]}":
            return "normalized_period_invalid", []
    return None, rows


def _find_manifest(output_root: Path, report_family: str) -> Path | None:
    latest_path = output_root / ("latest.json" if report_family == "performance" else f"{report_family}-latest.json")
    try:
        latest = _read_json(latest_path)
    except (OSError, ValueError, json.JSONDecodeError):
        latest = {}
    reference = latest.get("landing_manifest") if isinstance(latest, dict) else None
    candidate = PROJECT / reference if isinstance(reference, str) else None
    if candidate and candidate.is_file():
        return candidate
    paths = sorted((output_root / "landing").glob(f"eastmoney-{report_family}-*/manifest.json"))
    return paths[-1] if paths else None


def _report(report_family: str, *, status: str, blocking: list[str], manifest_path: Path | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION, "provider": "eastmoney_datacenter", "report_family": report_family,
        "landing_manifest": str(manifest_path) if manifest_path else None,
        "generated_at": datetime.now(timezone.utc).isoformat(), "status": status,
        "research_only": True, "formal_pit_verified": False,
        "target_period_count": 0, "completed_period_count": 0, "page_count": 0,
        "record_count": 0, "published_at_count": 0, "published_at_coverage": 0.0,
        "invalid_page_count": 0, "invalid_pages": [], "incomplete_periods": [],
        "blocking_reasons": blocking,
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("json_object_expected")
    return value


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
