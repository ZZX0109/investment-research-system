#!/usr/bin/env python3
"""Persist a current full A-share/ETF enumeration for the research master.

This is deliberately a current-enumeration input, not historical lifecycle
proof.  It expands the security-master denominator without inventing listing,
delisting, ST, or publication dates; those fields remain degraded until an
official historical source is verified.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService

ETF_NAMES = {
    "510050": "上证50ETF",
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "159915": "创业板ETF",
    "512100": "中证1000ETF",
}


def _normalise_rows(frame) -> list[dict]:
    if frame is None or frame.empty:
        return []
    records = frame.to_dict(orient="records")
    output: list[dict] = []
    for row in records:
        raw_code = row.get("code") or row.get("代码") or row.get("证券代码")
        if raw_code in (None, ""):
            continue
        code = str(raw_code).strip().rsplit(".", 1)[-1].zfill(6)
        name = row.get("name") or row.get("名称") or row.get("证券简称")
        output.append({
            "code": code,
            "code_name": str(name).strip() if name not in (None, "") else None,
            "instrument_type": "etf" if code in ETF_NAMES else "equity",
            "provider_as_of": "current_public_enumeration",
        })
    by_code = {row["code"]: row for row in output}
    for code, name in ETF_NAMES.items():
        by_code.setdefault(code, {
            "code": code,
            "code_name": name,
            "instrument_type": "etf",
            "provider_as_of": "configured_research_etf",
        })
    return [by_code[code] for code in sorted(by_code)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_security_master_universe")
    args = parser.parse_args()

    import akshare as ak

    rows = _normalise_rows(ak.stock_info_a_code_name())
    if not rows:
        raise SystemExit("current A-share enumeration is empty")
    now = datetime.now(timezone.utc)
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    uow = SQLiteUnitOfWork(args.database)
    try:
        service = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store))
        batch = service.persist(
            provider="akshare_cn_security_master",
            request_id=f"cn-security-master-universe-{now.date().isoformat()}-{uuid4()}",
            dataset="cn_security_master_research",
            payload=payload,
            schema_version="cn-security-master-current-enumeration-v1",
            symbol="CN-MASTER",
            available_at=now,
            received_at=now,
            market_session="research_backfill",
            data_tier=DataTier.RESEARCH_PIT,
        )
    finally:
        uow.close()

    args.output_root.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "cn-security-master-current-enumeration-v1",
        "status": "complete",
        "quality_status": "degraded",
        "research_only": True,
        "deployment_ready": False,
        "provider": "akshare_cn_security_master",
        "generated_at": now.isoformat(),
        "row_count": len(rows),
        "equity_count": sum(row["instrument_type"] == "equity" for row in rows),
        "etf_count": sum(row["instrument_type"] == "etf" for row in rows),
        "payload_hash": batch.payload_hash,
        "missing_reason_code": "current_enumeration_only",
        "missing_reason": "current public enumeration does not prove historical lifecycle or PIT publication time",
        "source_uri": "https://www.akshare.xyz/",
    }
    (args.output_root / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_root / "security_master_current.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
