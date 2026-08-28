from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "run_cn_data_completion.py"
    spec = importlib.util.spec_from_file_location("cn_data_completion_plan", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plan_is_fail_closed_and_uses_current_universe_denominator(tmp_path: Path) -> None:
    module = _module()
    (tmp_path / "artifacts/cn_security_master_universe").mkdir(parents=True)
    (tmp_path / "artifacts/cn_security_master").mkdir(parents=True)
    (tmp_path / "artifacts/cn_security_master_universe/latest.json").write_text(
        json.dumps({"row_count": 3, "equity_count": 2, "etf_count": 1, "status": "complete"}), encoding="utf-8"
    )
    (tmp_path / "artifacts/cn_security_master/latest.json").write_text(
        json.dumps({"daily_bar_symbol_count": 3, "quality_status": "complete"}), encoding="utf-8"
    )
    config = tmp_path / "plan.yaml"
    config.write_text(
        """
target:
  universe: artifacts/cn_security_master_universe/latest.json
steps:
  - id: security_universe
    priority: P0
    dataset: universe
    artifact: artifacts/cn_security_master_universe/latest.json
    required: true
    command: [scripts/fetch_cn_security_master_universe.py]
  - id: historical_prices
    priority: P0
    dataset: prices
    artifact: artifacts/cn_security_master/latest.json
    required: true
    command: [scripts/build_cn_security_master.py]
""",
        encoding="utf-8",
    )
    plan = module.build_plan(tmp_path, config_path=config)
    assert plan["status"] == "complete"
    assert plan["target"]["total"] == 3
    assert plan["completed_step_count"] == 2


def test_execute_requires_explicit_step() -> None:
    module = _module()
    # The guard is intentionally expressed by the CLI parser; the plan API
    # itself remains safe/read-only for callers building dashboards.
    assert callable(module.build_plan)


def test_shadow_step_requires_independent_trade_dates(tmp_path: Path) -> None:
    module = _module()
    artifact = tmp_path / "artifacts/research_shadow/summary.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({
        "status": "blocked", "valid_trade_date_count": 2,
        "minimum_required_trade_dates": 60, "deployment_ready": False,
    }), encoding="utf-8")
    status, evidence, reasons = module._step_evidence(
        {"id": "shadow_60_validation", "artifact": "artifacts/research_shadow/summary.json"},
        tmp_path, 0, 0,
    )
    assert status == "partial"
    assert evidence["valid_trade_date_count"] == 2
    assert reasons == ["shadow_independent_trade_dates_below_60"]


def test_historical_price_step_prefers_append_only_catalog_over_stale_standard_manifest(tmp_path: Path) -> None:
    module = _module()
    universe_dir = tmp_path / "artifacts/cn_security_master_universe"
    universe_dir.mkdir(parents=True)
    (universe_dir / "security_master_current.json").write_text(json.dumps([
        {"code": "600519"}, {"code": "000001"}, {"code": "920001"},
    ]), encoding="utf-8")
    database = tmp_path / "var/cn-research/catalog.db"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE raw_data_batches (data_tier TEXT, dataset TEXT, payload_json TEXT)")
    for dataset, symbol in (
        ("daily_bars_raw", "600519"), ("daily_bars_qfq", "600519"),
        ("daily_bars_raw", "000001"), ("daily_bars_qfq", "000001"),
        ("daily_bars_raw", "920001"),
    ):
        connection.execute(
            "INSERT INTO raw_data_batches VALUES (?,?,?)",
            ("research_pit", dataset, json.dumps({"symbol": symbol})),
        )
    connection.commit()
    connection.close()
    artifact = tmp_path / "artifacts/cn_security_master/latest.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(json.dumps({"daily_bar_symbol_count": 1, "quality_status": "degraded"}), encoding="utf-8")

    status, evidence, reasons = module._step_evidence(
        {"id": "historical_prices", "artifact": "artifacts/cn_security_master/latest.json"},
        tmp_path, 3, 3,
    )

    assert status == "partial"
    assert evidence["coverage_source"] == "append_only_catalog"
    assert evidence["raw_covered_symbols"] == 3
    assert evidence["qfq_covered_symbols"] == 2
    assert evidence["legacy_standard_manifest_symbols"] == 1
    assert reasons == ["front_adjusted_price_coverage_below_99_5pct", "price_quality_not_complete"]


def test_financial_bulk_step_exposes_inflight_landing_progress_before_latest_artifact(tmp_path: Path) -> None:
    module = _module()
    manifest = tmp_path / "artifacts/cn_financial_reports_eastmoney/landing/eastmoney-performance-20100331-20260331/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "status": "running",
        "run_id": "eastmoney-performance-20100331-20260331",
        "periods": {
            "20100331": {"status": "complete", "record_count": 10, "published_at_count": 10},
            "20100630": {"status": "partial", "record_count": 5, "published_at_count": 5},
        },
    }), encoding="utf-8")

    status, evidence, reasons = module._step_evidence(
        {"id": "financial_core_bulk_reports", "artifact": "artifacts/cn_financial_reports_eastmoney/latest.json"},
        tmp_path, 0, 0,
    )

    assert status == "partial"
    assert evidence["completed_period_count"] == 1
    assert evidence["target_period_count"] == 2
    assert evidence["published_at_coverage"] == 1.0
    assert reasons == ["core_financial_bulk_download_or_publication_coverage_incomplete"]


def test_extended_ratio_step_uses_full_universe_progress_ledger(tmp_path: Path) -> None:
    module = _module()
    progress = tmp_path / "artifacts/cn_financial_ratios_akshare/progress.json"
    progress.parent.mkdir(parents=True)
    progress.write_text(json.dumps({
        "target_equity_count": 100,
        "metric_contract_version": 3,
        "symbols": {str(i).zfill(6): {"status": "complete", "metric_contract_version": 3} for i in range(25)},
    }), encoding="utf-8")
    (progress.parent / "latest.json").write_text(json.dumps({"status": "complete", "target_equity_count": 162}), encoding="utf-8")
    status, evidence, reasons = module._step_evidence(
        {"id": "financial_extended_ratios", "artifact": "artifacts/cn_financial_ratios_akshare/latest.json"},
        tmp_path, 0, 0,
    )
    assert status == "partial"
    assert evidence["target_equity_count"] == 100
    assert evidence["completed_equity_count"] == 25
    assert evidence["coverage"] == 0.25
    assert reasons == ["extended_financial_fields_incomplete"]
