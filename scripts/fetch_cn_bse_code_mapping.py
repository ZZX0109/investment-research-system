#!/usr/bin/env python3
"""Ingest the official BSE 920-code migration table as research evidence.

The 2025 BSE migration changed the trading codes of existing listed companies
to the 920 range.  Retaining the official old/new mapping is necessary for
both historical security identity and resolving legacy public price endpoints.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from uuid import uuid4

import requests
from bs4 import BeautifulSoup

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService


SOURCE_URL = "https://www.bse.cn/service/code_mapping.html"


def _parse_mapping(html: bytes, *, source_url: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for table_row in soup.find_all("tr"):
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in table_row.find_all(["th", "td"])]
        codes = [cell for cell in cells if re.fullmatch(r"\d{6}", cell)]
        new_code = next((value for value in codes if value.startswith("920")), None)
        old_code = next((value for value in codes if value != new_code), None)
        if not new_code or not old_code or (old_code, new_code) in seen:
            continue
        seen.add((old_code, new_code))
        name = next((value for value in cells if value and not re.fullmatch(r"\d{6}", value) and not re.fullmatch(r"\d+", value) and not re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", value)), "")
        listed_on = next((value for value in cells if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", value)), "")
        rows.append({
            "old_code": old_code,
            "new_code": new_code,
            "security_name": name,
            "listed_on": listed_on.replace("/", "-"),
            "source_url": source_url,
            "data_tier": DataTier.RESEARCH_PIT.value,
        })
    return sorted(rows, key=lambda item: item["new_code"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", default=SOURCE_URL)
    parser.add_argument("--database", type=Path, default=PROJECT / "var/cn-research/catalog.db")
    parser.add_argument("--object-store", type=Path, default=PROJECT / "var/cn-research/raw")
    parser.add_argument("--output-root", type=Path, default=PROJECT / "artifacts/cn_bse_code_mapping")
    args = parser.parse_args()

    response = requests.get(
        args.source_url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; InvestmentResearch/1.0)"},
        timeout=(15, 45),
    )
    response.raise_for_status()
    rows = _parse_mapping(response.content, source_url=args.source_url)
    if not rows:
        raise RuntimeError("official BSE code-mapping page yielded no mappings")

    now = datetime.now(timezone.utc)
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()
    uow = SQLiteUnitOfWork(args.database)
    try:
        batch = RawPayloadIngestionService(uow, object_store=LocalObjectStore(args.object_store)).persist(
            provider="bse_official_code_mapping",
            request_id=f"bse-code-mapping-{uuid4()}",
            dataset="cn_bse_code_mapping_research",
            payload=payload,
            schema_version="cn-bse-code-mapping-v1",
            symbol="CN",
            available_at=now,
            received_at=now,
            market_session="research_backfill",
            data_tier=DataTier.RESEARCH_PIT,
        )
    finally:
        uow.close()

    args.output_root.mkdir(parents=True, exist_ok=True)
    (args.output_root / "mapping.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = {
        "schema_version": "cn-bse-code-mapping-v1",
        "data_tier": DataTier.RESEARCH_PIT.value,
        "research_only": True,
        "source_url": args.source_url,
        "mapping_count": len(rows),
        "raw_batch_id": str(batch.id),
        "payload_hash": batch.payload_hash,
        "generated_at": now.isoformat(),
        "status": "complete",
    }
    (args.output_root / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "mapping_count": len(rows), "output": str(args.output_root / "latest.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
