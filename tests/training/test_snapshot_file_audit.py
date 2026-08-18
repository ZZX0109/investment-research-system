from pathlib import Path

from investment_research.training.snapshot_landing import audit_file_contents


def test_snapshot_file_audit_detects_duplicate_and_ohlc_errors(tmp_path: Path) -> None:
    path = tmp_path / "bars.json"
    path.write_text(
        '[{"symbol":"000001","trade_date":"2026-08-17","open":10,"high":9,"low":8,"close":10},'
        '{"symbol":"000001","trade_date":"2026-08-17","open":10,"high":11,"low":8,"close":10}]',
        encoding="utf-8",
    )
    result = audit_file_contents(path, dataset="daily_bars_raw")
    assert result["schema_valid"] is True
    assert result["duplicate_key_count"] == 1
    assert result["ohlc_error_count"] == 1


def test_snapshot_file_audit_checks_adjustment_and_security_lifecycle(tmp_path: Path) -> None:
    path = tmp_path / "security_lifecycle.json"
    path.write_text(
        '[{"symbol":"000001","effective_from":"2026-08-10","effective_to":"2026-08-01"}]',
        encoding="utf-8",
    )
    result = audit_file_contents(path, dataset="cn_security_master_research")
    assert result["security_lifecycle_error_count"] == 1

    adjustment = tmp_path / "adjustment.json"
    adjustment.write_text(
        '[{"symbol":"000001","trade_date":"2026-08-10","raw_close":10,"adjusted_close":20,"adjustment_factor":1}]',
        encoding="utf-8",
    )
    result = audit_file_contents(adjustment, dataset="cn_adjustment_factors_research")
    assert result["adjustment_error_count"] == 1


def test_snapshot_file_audit_checks_cn_security_code_format(tmp_path: Path) -> None:
    path = tmp_path / "bars.json"
    path.write_text(
        '[{"symbol":"not-a-cn-code","trade_date":"2026-08-10","open":10,"high":11,"low":9,"close":10}]',
        encoding="utf-8",
    )
    result = audit_file_contents(path, dataset="daily_bars_raw")
    assert result["security_code_error_count"] == 1
