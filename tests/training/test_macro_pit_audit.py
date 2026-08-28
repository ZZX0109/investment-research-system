import json
import sqlite3
from pathlib import Path

from scripts.build_cn_macro_pit import build_report


def test_macro_audit_preserves_observation_and_blocks_missing_release_time(tmp_path: Path, monkeypatch) -> None:
    import scripts.build_cn_macro_pit as macro_pit

    monkeypatch.setattr(macro_pit, "PROJECT", tmp_path)
    raw_root = tmp_path / "raw"
    payload = raw_root / "raw-market" / "macro.json"
    payload.parent.mkdir(parents=True)
    payload.write_text(json.dumps([{"月份": "2026年07月份", "M2": 7.7}]), encoding="utf-8")
    database = tmp_path / "catalog.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE raw_data_batches (provider TEXT, dataset TEXT, available_at TEXT, payload_json TEXT)")
    connection.execute("INSERT INTO raw_data_batches VALUES (?, ?, ?, ?)", (
        "provider", "cn_macro_m2", "2026-08-01T00:00:00Z",
        json.dumps({"payload_ref": "file-object://raw-market/macro.json", "payload_hash": "a" * 64, "fetched_at": "2026-08-01T00:00:00Z"}),
    ))
    connection.commit()
    connection.close()

    report = macro_pit.build_report(database, raw_root, tmp_path / "out")

    assert report["record_count"] == 1
    assert report["published_at_coverage"] == 0.0
    assert report["quality_status"] == "degraded"
    row = json.loads((tmp_path / "out/macro_pit.jsonl").read_text().splitlines()[0])
    assert row["observation_period"] == "2026-07-01"
    assert row["missing_reason_code"] == "published_time_unverified"


def test_macro_audit_merges_official_retry_evidence_without_collapsing_daily_rows(tmp_path: Path, monkeypatch) -> None:
    """PBC/CFETS retry evidence is additive and keeps daily PIT keys exact."""
    import scripts.build_cn_macro_pit as macro_pit

    monkeypatch.setattr(macro_pit, "PROJECT", tmp_path)
    raw_root = tmp_path / "raw"
    payload = raw_root / "raw-market" / "macro.json"
    payload.parent.mkdir(parents=True)
    payload.write_text(json.dumps([
        {"日期": "2026-07-20", "LPR1Y": 3.0},
        {"日期": "2026-07-21", "LPR1Y": 3.0},
    ]), encoding="utf-8")
    evidence = tmp_path / "artifacts/subagent_macro_history_retry/normalized/release_date_mapping.jsonl"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("\n".join([
        json.dumps({
            "baseline_dataset": "cn_macro_lpr", "observation_period": "2026-07-20",
            "published_at": None, "evidence_level": "date_level",
            "timestamp_precision": "date", "status": "mapped",
        }),
        json.dumps({
            "baseline_dataset": "cn_macro_lpr", "observation_period": "2026-07-21",
            "published_at": "2026-07-21T09:15:00+08:00", "evidence_level": "actual",
            "evidence_subtype": "official_fixed_time_rule", "timestamp_precision": "minute_rule_derived",
            "status": "mapped", "source_url": "https://example.invalid/lpr",
        }),
    ]) + "\n", encoding="utf-8")
    database = tmp_path / "catalog.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE raw_data_batches (provider TEXT, dataset TEXT, available_at TEXT, payload_json TEXT)")
    connection.execute("INSERT INTO raw_data_batches VALUES (?, ?, ?, ?)", (
        "provider", "cn_macro_lpr", "2026-08-01T00:00:00Z",
        json.dumps({"payload_ref": "file-object://raw-market/macro.json", "payload_hash": "b" * 64, "fetched_at": "2026-08-01T00:00:00Z"}),
    ))
    connection.commit()
    connection.close()

    report = macro_pit.build_report(database, raw_root, tmp_path / "out")
    rows = [json.loads(line) for line in (tmp_path / "out/macro_pit.jsonl").read_text().splitlines()]

    assert report["published_at_coverage"] == 0.5
    assert rows[0]["observation_period"] == "2026-07-20"
    assert rows[0]["published_at"] is None
    assert rows[0]["publication_evidence_level"] == "date_level"
    assert rows[1]["observation_period"] == "2026-07-21"
    assert rows[1]["published_at"] == "2026-07-21T09:15:00+08:00"
    assert rows[1]["publication_timestamp_precision"] == "minute_rule_derived"


def test_unresolved_nbs_article_does_not_shadow_verified_retry_timestamp(tmp_path: Path, monkeypatch) -> None:
    import scripts.build_cn_macro_pit as macro_pit

    monkeypatch.setattr(macro_pit, "PROJECT", tmp_path)
    raw_root = tmp_path / "raw"
    payload = raw_root / "raw-market" / "macro.json"
    payload.parent.mkdir(parents=True)
    payload.write_text(json.dumps([{"月份": "2026年07月份", "M2": 7.7}]), encoding="utf-8")
    actual = tmp_path / "artifacts/cn_macro_actual_release_nbs/actual_releases.json"
    actual.parent.mkdir(parents=True)
    actual.write_text(json.dumps([{
        "series": "m2", "observation_period": "2026-07-01", "published_at": None,
    }]), encoding="utf-8")
    evidence = tmp_path / "artifacts/subagent_macro_history_retry/normalized/release_date_mapping.jsonl"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(json.dumps({
        "baseline_dataset": "cn_macro_m2", "observation_period": "2026-07-01",
        "published_at": "2026-08-10T09:00:00+08:00", "evidence_level": "actual",
        "status": "mapped", "source_url": "https://example.invalid/m2",
    }) + "\n", encoding="utf-8")
    database = tmp_path / "catalog.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE raw_data_batches (provider TEXT, dataset TEXT, available_at TEXT, payload_json TEXT)")
    connection.execute("INSERT INTO raw_data_batches VALUES (?, ?, ?, ?)", (
        "provider", "cn_macro_m2", "2026-08-01T00:00:00Z",
        json.dumps({"payload_ref": "file-object://raw-market/macro.json", "payload_hash": "c" * 64, "fetched_at": "2026-08-01T00:00:00Z"}),
    ))
    connection.commit()
    connection.close()

    report = macro_pit.build_report(database, raw_root, tmp_path / "out")
    row = json.loads((tmp_path / "out/macro_pit.jsonl").read_text().splitlines()[0])
    assert report["published_at_coverage"] == 1.0
    assert row["published_at"] == "2026-08-10T09:00:00+08:00"
