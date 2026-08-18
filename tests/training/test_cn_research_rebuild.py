from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

from investment_research.domain.data_tier import DataTier
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.object_store import LocalObjectStore
from investment_research.service.trusted_ingestion import RawPayloadIngestionService
from investment_research.training.parquet_store import PITParquetStore


def test_cn_research_rebuild_binds_rows_to_one_immutable_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "research.db"
    raw_root = tmp_path / "raw"
    parquet_root = tmp_path / "parquet"
    output_root = tmp_path / "artifacts"
    days = _business_days(date(2025, 1, 2), 290)
    uow = SQLiteUnitOfWork(database)
    ingestion = RawPayloadIngestionService(uow, object_store=LocalObjectStore(raw_root))
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    for symbol, base in (("600000", 10.0), ("510300", 4.0)):
        payload = json.dumps([
            {
                "日期": day.isoformat(), "开盘": base + index * 0.01,
                "最高": base + index * 0.01 + 0.1, "最低": base + index * 0.01 - 0.1,
                "收盘": base + index * 0.01 + 0.02, "成交量": 1_000_000 + index,
                "成交额": 100_000_000 + index * 1000, "交易状态": "1",
            }
            for index, day in enumerate(days)
        ], ensure_ascii=False).encode()
        for adjustment_mode in ("raw", "qfq"):
            ingestion.persist(
                provider="akshare", request_id=f"fixture-{symbol}-{adjustment_mode}",
                dataset=f"daily_bars_{adjustment_mode}", payload=payload,
                schema_version="test-fixture-v1", symbol=symbol,
                available_at=now, received_at=now, data_tier=DataTier.RESEARCH_PIT,
            )
            incremental = json.dumps(json.loads(payload)[-10:], ensure_ascii=False).encode()
            ingestion.persist(
                provider="baostock", request_id=f"incremental-{symbol}-{adjustment_mode}",
                dataset=f"daily_bars_{adjustment_mode}", payload=incremental,
                schema_version="test-fixture-v1", symbol=symbol,
                available_at=now + timedelta(seconds=1), received_at=now + timedelta(seconds=1),
                data_tier=DataTier.RESEARCH_PIT,
            )
    assert len(uow.trusted_market.raw_batches(dataset="daily_bars_raw", data_tier="research_pit")) == 4
    uow.close()

    project = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [
            sys.executable, str(project / "scripts/rebuild_cn_research_pit.py"),
            "--database", str(database), "--raw-object-store", str(raw_root),
            "--research-object-store", str(parquet_root), "--output-root", str(output_root),
            "--coverage-ledger", str(tmp_path / "missing-coverage.json"),
            "--as-of", days[-1].isoformat(), "--max-equities", "1",
                "--minimum-equities", "1",
                "--minimum-history-sessions", "250",
            "--minimum-training-sessions", "250",
            "--allow-current-cohort-breadth",
        ],
        cwd=project, text=True, capture_output=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    index = json.loads(Path(completed.stdout.strip()).read_text(encoding="utf-8"))
    assert index["data_tier"] == "research_pit"
    assert index["deployment_ready"] is False
    assert set(index["contexts"]) == {"close_confirmed"}
    close = index["contexts"]["close_confirmed"]
    standard_manifest = next(
        json.loads(Path(ref).read_text(encoding="utf-8"))
        for ref in index["standard_manifest_refs"]
        if "600000" in Path(ref).name
    )
    assert standard_manifest["row_count"] == 290
    assert len(standard_manifest["raw_input_batches"]) == 2
    assert len(standard_manifest["qfq_input_batches"]) == 2
    manifests = close["sample_manifests"]["cn_equity_core"]
    assert manifests
    manifest = json.loads(Path(manifests[-1]).read_text(encoding="utf-8"))
    rows = PITParquetStore(LocalObjectStore(parquet_root)).read_partition(manifest["sample_parquet_ref"])
    assert rows
    assert {row["market_snapshot_id"] for row in rows} == {close["snapshot_id"]}
    assert {row["market_snapshot_hash"] for row in rows} == {close["snapshot_hash"]}
    assert {row["data_tier"] for row in rows} == {"research_pit"}
    assert {row["data_quality_status"] for row in rows} == {"degraded"}
    assert all(
        json.loads(row["event_missing_mask"]).get("event_source_unavailable") == 1.0
        if isinstance(row["event_missing_mask"], str)
        else row["event_missing_mask"].get("event_source_unavailable") == 1.0
        for row in rows
    )
    etf_manifests = close["sample_manifests"]["cn_etf_benchmark"]
    assert etf_manifests
    etf_manifest = json.loads(Path(etf_manifests[-1]).read_text(encoding="utf-8"))
    assert etf_manifest["cohort_role"] == "benchmark_only"
    assert etf_manifest["ranking_label_eligible"] is False
    etf_rows = PITParquetStore(LocalObjectStore(parquet_root)).read_partition(etf_manifest["sample_parquet_ref"])
    assert etf_rows
    assert all(
        (json.loads(row["labels"]) if isinstance(row["labels"], str) else row["labels"])["long_term_label_available"] is False
        for row in etf_rows
    )
    leakage = json.loads(Path(close["leakage_report_ref"]).read_text(encoding="utf-8"))
    assert leakage["research_error_count"] == 0
    assert leakage["formal_release_blocked"] is True


def _business_days(start: date, count: int) -> list[date]:
    output: list[date] = []
    current = start
    while len(output) < count:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return output
