import json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timezone

from investment_research.domain.data_tier import DataTier
from investment_research.domain.trusted_market import RawDataBatch
from investment_research.repository.sqlite import SQLiteUnitOfWork
from investment_research.service.research_data_quality import (
    build_current_research_discovery,
    build_free_research_data_quality,
    eligibility_for_symbol,
    load_free_research_catalog_batches,
)


def _batch(dataset: str, symbol: str) -> SimpleNamespace:
    return SimpleNamespace(dataset=dataset, symbol=symbol)


def _write_artifact(root: Path, name: str, payload: dict) -> None:
    path = root / "artifacts" / name / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _dataset(report: dict, identifier: str) -> dict:
    return next(item for item in report["datasets"] if item["id"] == identifier)


def test_symbol_eligibility_never_substitutes_raw_for_qfq_or_bse_scope() -> None:
    raw = {"600519", "920001"}
    qfq = {"600519"}

    hushen = eligibility_for_symbol("600519", raw_symbols=raw, qfq_symbols=qfq)
    bse = eligibility_for_symbol("920001", raw_symbols=raw, qfq_symbols=qfq)

    assert hushen["quote_research_eligible"]
    assert hushen["return_backtest_eligible"]
    assert hushen["model_eligible"]
    assert bse["quote_research_eligible"]
    assert not bse["return_backtest_eligible"]
    assert not bse["model_eligible"]
    assert "outside_free_model_scope_bse_or_non_a_share" in bse["blocking_reasons"]
    assert "front_adjusted_price_series_missing" in bse["blocking_reasons"]


def test_quality_inventory_preserves_price_scope_and_artifact_gaps(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "cn_security_lifecycle_akshare", {
        "status": "partial", "target_equity_count": 3,
        "listing_date_coverage": 0.8, "delisting_date_coverage": 0.0,
        "industry_history_coverage": 0.0, "st_status_coverage": 0.0,
        "code_change_coverage": 0.2, "published_at_coverage": 0.0,
        "missing_reason_code": "historical_lifecycle_partial",
        "generated_at": "2026-08-24T00:00:00+00:00",
    })
    _write_artifact(tmp_path, "cn_financial_coverage", {
        "status": "degraded", "target_field_count": 100,
        "observed_field_count": 98, "coverage": 0.98,
        "published_at_coverage": 0.0, "pit_verified": False,
        "missing_reason_code": "published_time_unverified",
    })
    _write_artifact(tmp_path, "cn_corporate_actions_detailed", {
        "status": "partial", "target_equity_count": 3,
        "completed_equity_count": 1,
    })
    _write_artifact(tmp_path, "cn_event_backfill_full", {
        "status": "complete", "target_equity_count": 1,
        "completed_equity_count": 1,
    })
    _write_artifact(tmp_path, "cn_macro_actual_release_nbs", {
        "status": "partial", "record_count": 10,
        "verified_pubdate_count": 4, "published_at_coverage": 0.4,
    })
    progress = tmp_path / "artifacts" / "cn_financial_ratios_akshare" / "progress.json"
    progress.parent.mkdir(parents=True)
    progress.write_text(json.dumps({
        "metric_contract_version": 3,
        "target_equity_count": 3,
        "updated_at": "2026-08-24T01:00:00+00:00",
        "symbols": {
            "000001": {"status": "complete", "metric_contract_version": 3},
            "000002": {"status": "complete", "metric_contract_version": 2},
        },
    }), encoding="utf-8")
    bulk_manifest = tmp_path / "artifacts" / "cn_financial_reports_eastmoney" / "landing" / "test-run" / "manifest.json"
    bulk_manifest.parent.mkdir(parents=True)
    bulk_manifest.write_text(json.dumps({
        "periods": {
            "20240331": {"status": "complete", "record_count": 10, "published_at_count": 10},
            "20240630": {"status": "pending", "record_count": 0, "published_at_count": 0},
        },
    }), encoding="utf-8")

    report = build_free_research_data_quality(
        project_root=tmp_path,
        raw_batches=[
            _batch("daily_bars_raw", "600519"),
            _batch("daily_bars_qfq", "600519"),
            _batch("daily_bars_raw", "000001"),
            _batch("daily_bars_qfq", "000001"),
            _batch("daily_bars_raw", "920001"),
        ],
    )

    assert report["status"] == "research_only"
    assert report["model_backtest_scope"]["eligible_symbol_count"] == 2
    assert report["quote_only_scope"]["raw_symbol_count"] == 1
    assert report["quote_only_scope"]["qfq_missing_symbol_count"] == 1
    assert _dataset(report, "raw_prices")["coverage_ratio"] == 1.0
    assert _dataset(report, "hushen_qfq_prices")["status"] == "available"
    assert _dataset(report, "outside_scope_adjusted_prices")["status"] == "blocked"
    financials = _dataset(report, "financial_fields")
    assert financials["coverage_ratio"] == 0.98
    assert financials["published_at_coverage"] == 0.0
    assert financials["pit_verified"] is False
    ratio_backfill = _dataset(report, "financial_ratio_backfill")
    assert ratio_backfill["status"] == "partial"
    assert ratio_backfill["available_count"] == 1
    assert ratio_backfill["coverage_ratio"] == 1 / 3
    core_bulk = _dataset(report, "financial_core_bulk_backfill")
    assert core_bulk["status"] == "partial"
    assert core_bulk["available_count"] == 1
    assert core_bulk["coverage_ratio"] == 1 / 2
    assert core_bulk["published_at_coverage"] == 1.0
    statement_bulk = _dataset(report, "financial_statement_bulk_backfill")
    assert statement_bulk["status"] == "partial"
    assert statement_bulk["available_count"] == 1
    assert statement_bulk["target_count"] == 8
    assert statement_bulk["coverage_ratio"] == 1 / 8
    assert "published_time_unverified" in report["blocking_reasons"]


def test_quality_inventory_prefers_unified_macro_pit_evidence(tmp_path: Path) -> None:
    _write_artifact(tmp_path, "cn_macro_actual_release_nbs", {
        "status": "partial", "record_count": 10,
        "verified_pubdate_count": 1, "published_at_coverage": 0.1,
    })
    path = tmp_path / "artifacts/cn_research_auxiliary/macro_pit_latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "status": "degraded", "record_count": 100,
        "published_at_coverage": 0.62,
        "source_release_date_coverage": 0.05,
        "planned_published_at_coverage": 0.1,
        "revision_coverage": 1.0,
        "missing_reason_code": "published_time_unverified",
    }), encoding="utf-8")

    report = build_free_research_data_quality(project_root=tmp_path, raw_batches=[])
    macro = _dataset(report, "macro_release_times")

    assert macro["target_count"] == 100
    assert macro["available_count"] == 62
    assert macro["coverage_ratio"] == 0.62
    assert macro["dimensions"]["source_release_date_coverage"] == 0.05


def test_quality_inventory_exposes_sample_layer_snapshot_binding(tmp_path: Path) -> None:
    root = tmp_path / "artifacts" / "free_research_rebuild_all_raw_standard"
    root.mkdir(parents=True)
    cohort = root / "cohort.json"
    cohort.write_text(json.dumps({"members": [{"symbol": "600519"}, {"symbol": "000001"}]}), encoding="utf-8")
    child = root / "sample.json"
    child.write_text(json.dumps({
        "symbol": "600519", "market_snapshot_id": "snapshot-1", "market_snapshot_hash": "a" * 64,
    }), encoding="utf-8")
    (root / "latest.json").write_text(json.dumps({
        "status": "research_only",
        "as_of": "2026-08-21",
        "cohort_refs": {"cn_equity_core": str(cohort)},
        "contexts": {"close_confirmed": {
            "snapshot_id": "snapshot-1", "snapshot_hash": "b" * 64,
            "sample_manifests": {"cn_equity_core": [str(child)]},
        }},
    }), encoding="utf-8")
    staging = tmp_path / "artifacts" / "free_research_sample_batches" / "stage" / "samples" / "close_confirmed" / "cn_equity_core" / "000001"
    staging.mkdir(parents=True)
    (staging / "2026.json").write_text(json.dumps({
        "symbol": "000001", "market_snapshot_id": "snapshot-1",
        "market_snapshot_hash": "b" * 64, "sample_parquet_ref": "file-object://staged",
    }), encoding="utf-8")

    report = build_free_research_data_quality(project_root=tmp_path, raw_batches=[])
    samples = _dataset(report, "research_sample_layer")
    assert samples["status"] == "partial"
    assert samples["target_count"] == 2
    assert samples["available_count"] == 1
    assert samples["dimensions"]["bound_manifest_count"] == 0
    assert samples["dimensions"]["staging_symbol_count"] == 1
    assert "research_sample_manifests_missing_or_unbound" in samples["blocking_reasons"]
    assert "sample_batches_staging_not_promoted" in samples["blocking_reasons"]


def test_catalog_loader_is_read_only_and_uses_the_dedicated_research_catalog(tmp_path: Path) -> None:
    database = tmp_path / "cn-research" / "catalog.db"
    database.parent.mkdir()
    now = datetime(2026, 8, 24, tzinfo=timezone.utc)
    uow = SQLiteUnitOfWork(database)
    try:
        uow.trusted_market.add_raw_batch(RawDataBatch(
            provider="fixture", request_id="raw-600519", dataset="daily_bars_raw",
            payload_ref="file-object://fixture", payload_hash="a" * 64,
            schema_version="fixture-v1", symbol="600519", fetched_at=now,
            available_at=now, data_tier=DataTier.RESEARCH_PIT,
            time_semantics="test_fixture",
        ))
    finally:
        uow.close()

    before = database.stat()
    batches = load_free_research_catalog_batches(database)
    after = database.stat()

    assert [batch.symbol for batch in batches] == ["600519"]
    assert after.st_size == before.st_size
    assert after.st_mtime_ns == before.st_mtime_ns


def test_current_discovery_lists_the_full_public_enumeration_with_scope_labels(tmp_path: Path) -> None:
    master = tmp_path / "artifacts" / "cn_security_master_universe"
    master.mkdir(parents=True)
    (master / "security_master_current.json").write_text(json.dumps([
        {"code": "600519", "code_name": "贵州茅台", "instrument_type": "equity"},
        {"code": "920001", "code_name": "北交所样本", "instrument_type": "equity"},
        {"code": "510300", "code_name": "沪深300ETF", "instrument_type": "etf"},
    ], ensure_ascii=False), encoding="utf-8")
    (master / "latest.json").write_text(json.dumps({
        "provider": "akshare_cn_security_master",
        "generated_at": "2026-08-24T00:00:00+00:00",
        "missing_reason_code": "current_enumeration_only",
    }), encoding="utf-8")

    report = build_current_research_discovery(
        project_root=tmp_path,
        raw_batches=[
            _batch("daily_bars_raw", "600519"),
            _batch("daily_bars_qfq", "600519"),
            _batch("daily_bars_raw", "920001"),
            _batch("daily_bars_raw", "510300"),
            _batch("daily_bars_qfq", "510300"),
        ],
        query="",
        limit=20,
    )

    assert report["status"] == "research_only"
    assert report["counts"] == {
        "current_universe": 3,
        "quote_research_eligible": 3,
        "return_backtest_eligible": 2,
        "model_eligible": 2,
        "quote_only": 1,
        "matched": 3,
        "displayed": 3,
    }
    bse = next(item for item in report["symbols"] if item["symbol"] == "920001")
    assert bse["exchange"] == "XBSE"
    assert bse["quote_research_eligible"] is True
    assert bse["model_eligible"] is False
    assert "current_enumeration_only_not_historical_membership_or_pit_proof" in report["blocking_reasons"]

    search = build_current_research_discovery(
        project_root=tmp_path,
        raw_batches=[_batch("daily_bars_raw", "600519"), _batch("daily_bars_qfq", "600519")],
        query="茅台",
        limit=1,
    )
    assert search["counts"]["matched"] == 1
    assert search["symbols"][0]["symbol"] == "600519"

    quote_only = build_current_research_discovery(
        project_root=tmp_path,
        raw_batches=[
            _batch("daily_bars_raw", "600519"), _batch("daily_bars_qfq", "600519"),
            _batch("daily_bars_raw", "920001"),
        ],
        asset_type="equity",
        eligibility="quote_only",
        limit=20,
    )
    assert quote_only["filters"] == {"query": "", "asset_type": "equity", "eligibility": "quote_only"}
    assert quote_only["counts"]["matched"] == 1
    assert [item["symbol"] for item in quote_only["symbols"]] == ["920001"]


def test_current_discovery_keeps_filter_contract_when_master_is_unavailable(tmp_path: Path) -> None:
    report = build_current_research_discovery(
        project_root=tmp_path,
        raw_batches=[],
        query="茅台",
        asset_type="invalid",
        eligibility="model",
    )

    assert report["status"] == "unavailable"
    assert report["filters"] == {"query": "茅台", "asset_type": "all", "eligibility": "model"}
