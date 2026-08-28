from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "audit_project_completion.py"
    spec = importlib.util.spec_from_file_location("project_completion", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_completion_matrix_preserves_missing_data_and_thresholds(tmp_path: Path) -> None:
    module = _module()
    artifacts = tmp_path / "artifacts"
    (artifacts / "download_manifests").mkdir(parents=True)
    (artifacts / "cn_financial_coverage").mkdir(parents=True)
    (artifacts / "cn_security_master").mkdir(parents=True)
    (artifacts / "cn_trading_status").mkdir(parents=True)
    (artifacts / "cn_research_auxiliary").mkdir(parents=True)
    (artifacts / "long_term_readiness").mkdir(parents=True)
    (artifacts / "long_term_model_registry").mkdir(parents=True)
    (artifacts / "long_term_training").mkdir(parents=True)
    (artifacts / "download_manifests/latest.json").write_text(json.dumps({"target_symbol_count": 100, "successful_target_symbol_count": 99}), encoding="utf-8")
    (artifacts / "cn_financial_coverage/latest.json").write_text(json.dumps({"coverage": 0.99, "pit_verified": True}), encoding="utf-8")
    (artifacts / "cn_security_master/latest.json").write_text(json.dumps({"symbol_count": 100, "industry_mapped_count": 100, "st_status_coverage": 1, "delisting_coverage": 1, "code_change_coverage": 1}), encoding="utf-8")
    (artifacts / "cn_trading_status/latest.json").write_text(json.dumps({"published_at_coverage": 1}), encoding="utf-8")
    (artifacts / "cn_research_auxiliary/macro_pit_latest.json").write_text(json.dumps({"published_at_coverage": 1}), encoding="utf-8")
    checks = [{"name": "event_missing_semantics", "status": "passed"}, {"name": "active_snapshot_gate", "status": "passed", "evidence": {"pit_leakage_error_count": 0}}, {"name": "long_term_model_evaluation_contract", "status": "passed"}]
    (artifacts / "long_term_readiness/latest.json").write_text(json.dumps({"checks": checks}), encoding="utf-8")
    (artifacts / "long_term_model_registry/latest.json").write_text(json.dumps({"tasks": list(module.CANONICAL_TASKS), "deployment_ready": False}), encoding="utf-8")
    (artifacts / "long_term_training/latest.json").write_text("{}", encoding="utf-8")

    report = module.build_report(tmp_path)
    assert report["status"] == "blocked"
    missing_ids = {item["id"] for item in report["missing_data"]}
    assert "price_coverage" in missing_ids
    assert "freshness" in missing_ids
    assert "agent_evidence" in missing_ids
    financial = next(item for item in report["requirements"] if item["id"] == "financial_core")
    assert financial["observed"] == 0.99
    assert financial["target"] == 0.98


def test_completion_matrix_excludes_etfs_from_company_industry_denominator(tmp_path: Path) -> None:
    module = _module()
    artifacts = tmp_path / "artifacts"
    for name in (
        "download_manifests", "cn_financial_coverage", "cn_security_master",
        "cn_trading_status", "cn_research_auxiliary", "long_term_readiness",
        "long_term_model_registry", "long_term_training",
    ):
        (artifacts / name).mkdir(parents=True)
    (tmp_path / "config").mkdir()
    (tmp_path / "config/cn_research_target_167_symbols.json").write_text(
        json.dumps({"cn": ["000001", "510300"]}), encoding="utf-8"
    )
    (artifacts / "download_manifests/latest.json").write_text(json.dumps({
        "target_symbol_count": 2, "successful_target_symbol_count": 2,
        "generated_at": "2026-08-21T18:00:00+00:00",
        "records": [
            {"category": "prices", "symbol": "000001", "date_end": "2026-08-21"},
            {"category": "prices", "symbol": "510300", "date_end": "2026-08-21"},
        ],
    }), encoding="utf-8")
    (artifacts / "cn_financial_coverage/latest.json").write_text(json.dumps({"coverage": 0.99, "pit_verified": True}), encoding="utf-8")
    (artifacts / "cn_security_master/latest.json").write_text(json.dumps({
        "symbol_count": 2, "industry_mapped_count": 1,
        "industry_coverage_applicable": 1.0,
        "st_status_coverage": 1, "delisting_coverage": 1, "code_change_coverage": 1,
    }), encoding="utf-8")
    (artifacts / "cn_trading_status/latest.json").write_text(json.dumps({"published_at_coverage": 1}), encoding="utf-8")
    (artifacts / "cn_research_auxiliary/macro_pit_latest.json").write_text(json.dumps({"published_at_coverage": 1}), encoding="utf-8")
    checks = [
        {"name": "event_missing_semantics", "status": "passed"},
        {"name": "active_snapshot_gate", "status": "passed", "evidence": {"pit_leakage_error_count": 0}},
        {"name": "long_term_model_evaluation_contract", "status": "passed"},
    ]
    (artifacts / "long_term_readiness/latest.json").write_text(json.dumps({"checks": checks}), encoding="utf-8")
    (artifacts / "long_term_model_registry/latest.json").write_text(json.dumps({"tasks": list(module.CANONICAL_TASKS), "deployment_ready": False}), encoding="utf-8")
    (artifacts / "long_term_training/latest.json").write_text("{}", encoding="utf-8")
    report = module.build_report(tmp_path)
    industry = next(item for item in report["requirements"] if item["id"] == "industry_coverage")
    assert industry["status"] == "passed"
    assert industry["observed"] == 1.0


def test_completion_matrix_uses_catalog_for_current_price_coverage(tmp_path: Path) -> None:
    module = _module()
    universe_dir = tmp_path / "artifacts/cn_security_master_universe"
    universe_dir.mkdir(parents=True)
    (universe_dir / "latest.json").write_text(
        json.dumps({"row_count": 3, "equity_count": 3, "etf_count": 0}), encoding="utf-8"
    )
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

    report = module.build_report(tmp_path)
    raw = next(item for item in report["requirements"] if item["id"] == "full_universe_price_coverage")
    qfq = next(item for item in report["requirements"] if item["id"] == "full_universe_qfq_coverage")

    assert raw["status"] == "passed"
    assert raw["observed"]["raw_covered_symbols"] == 3
    assert raw["observed"]["source"] == "append_only_catalog"
    assert qfq["status"] == "missing"
    assert qfq["observed"]["qfq_covered_symbols"] == 2


def test_completion_matrix_does_not_trust_legacy_ratio_latest_for_full_universe(tmp_path: Path) -> None:
    module = _module()
    artifacts = tmp_path / "artifacts"
    for name in (
        "download_manifests", "cn_financial_coverage", "cn_security_master",
        "cn_trading_status", "cn_research_auxiliary", "long_term_readiness",
        "long_term_model_registry", "long_term_training", "cn_financial_ratios_akshare",
    ):
        (artifacts / name).mkdir(parents=True)
    (artifacts / "download_manifests/latest.json").write_text(json.dumps({"target_symbol_count": 1, "successful_target_symbol_count": 1}), encoding="utf-8")
    (artifacts / "cn_financial_coverage/latest.json").write_text(json.dumps({"coverage": 1.0, "pit_verified": False}), encoding="utf-8")
    (artifacts / "cn_financial_ratios_akshare/progress.json").write_text(json.dumps({
        "target_equity_count": 100, "metric_contract_version": 3,
        "symbols": {str(i).zfill(6): {"status": "complete", "metric_contract_version": 3} for i in range(10)},
    }), encoding="utf-8")
    (artifacts / "cn_security_master/latest.json").write_text(json.dumps({"symbol_count": 1, "industry_coverage_applicable": 1, "st_status_coverage": 1, "delisting_coverage": 1, "code_change_coverage": 1}), encoding="utf-8")
    (artifacts / "cn_trading_status/latest.json").write_text(json.dumps({"published_at_coverage": 1}), encoding="utf-8")
    (artifacts / "cn_research_auxiliary/macro_pit_latest.json").write_text(json.dumps({"published_at_coverage": 1}), encoding="utf-8")
    (artifacts / "long_term_readiness/latest.json").write_text(json.dumps({"checks": []}), encoding="utf-8")
    (artifacts / "long_term_model_registry/latest.json").write_text(json.dumps({"tasks": list(module.CANONICAL_TASKS), "deployment_ready": False}), encoding="utf-8")
    report = module.build_report(tmp_path)
    extended = next(item for item in report["requirements"] if item["id"] == "financial_extended")
    assert extended["status"] == "missing"
    assert extended["observed"]["all_universe_ratio_progress"]["coverage"] == 0.1
