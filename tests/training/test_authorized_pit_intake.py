from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "ingest_authorized_pit_source.py"
    spec = importlib.util.spec_from_file_location("authorized_pit_intake", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(module, *, revision: str = "r1", supersedes: str | None = None, available: str = "2026-08-01T09:00:00Z") -> dict:
    row = {
        "dataset": "cn_financial_authorized",
        "symbol": "000001",
        "observation_period": "2026-06-30",
        "effective_at": "2026-06-30T00:00:00Z",
        "published_at": "2026-08-01T08:00:00Z",
        "available_at": available,
        "fetched_at": "2026-08-01T10:00:00Z" if available == "2026-08-01T09:00:00Z" else "2026-08-03T10:00:00Z",
        "revision_id": revision,
        "raw_payload_hash": "a" * 64,
        "quality_status": "complete",
        "source_provider": "licensed-test-provider",
        "source_uri": "https://provider.example/pit",
        "license_scope": "internal-research",
    }
    if supersedes is not None:
        row["supersedes_revision_id"] = supersedes
    row["normalized_record_hash"] = module._normalized_record_hash(row)
    return row


def _attestation() -> dict:
    return {
        "attestation_id": "att-2026-08",
        "provider": "licensed-test-provider",
        "source_uri": "https://provider.example/pit",
        "license_scope": "internal-research",
        "authorized": True,
        "historical_available_at": True,
        "publication_timestamps": True,
        "revision_history": True,
        "valid_from": "2026-01-01T00:00:00Z",
    }


def _run(module, tmp_path: Path, input_path: Path, *, attestation: dict | None = None) -> tuple[int, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    attestation_path = tmp_path / "attestation.json"
    attestation_path.write_text(json.dumps(_attestation() if attestation is None else attestation), encoding="utf-8")
    output = tmp_path / "latest.json"
    code = module.main([
        "--input", str(input_path),
        "--attestation", str(attestation_path),
        "--provider", "licensed-test-provider",
        "--dataset", "cn_financial_authorized",
        "--source-uri", "https://provider.example/pit",
        "--license-scope", "internal-research",
        "--landing-root", str(tmp_path / "landing"),
        "--output", str(output),
        "--run-id", "test-run",
    ])
    return code, json.loads(output.read_text(encoding="utf-8"))


def test_valid_attested_jsonl_is_staged_but_not_activated(tmp_path: Path) -> None:
    module = _module()
    rows = [_record(module), _record(module, revision="r2", supersedes="r1", available="2026-08-02T09:00:00Z")]
    source = tmp_path / "rows.jsonl"
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    code, report = _run(module, tmp_path, source)

    assert code == module.EXIT_READY
    assert report["status"] == "ready_for_pit"
    assert report["formal_pit_verified"] is True
    assert report["active_snapshot_eligible"] is False
    assert report["coverage"] == {
        "published_at": 1.0,
        "available_at": 1.0,
        "revision_id": 1.0,
        "normalized_record_hash": 1.0,
    }
    normalized = Path(report["artifacts"]["normalized_records_ref"])
    assert normalized.is_file()
    assert len(normalized.read_text(encoding="utf-8").splitlines()) == 2
    assert len(report["manifest_sha256"]) == 64


def test_missing_authorization_is_blocked_without_landing_bytes(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(_record(module)) + "\n", encoding="utf-8")
    attestation = _attestation()
    attestation["authorized"] = False

    code, report = _run(module, tmp_path, source, attestation=attestation)

    assert code == module.EXIT_BLOCKED
    assert report["status"] == "blocked"
    assert report["blocking_reasons"] == ["authorization_attestation_not_authorized"]
    assert not list((tmp_path / "landing").rglob("*")) if (tmp_path / "landing").exists() else True


def test_temporal_contract_failure_is_blocked(tmp_path: Path) -> None:
    module = _module()
    row = _record(module)
    row["available_at"] = "2026-08-01T07:00:00Z"
    source = tmp_path / "rows.json"
    source.write_text(json.dumps([row]), encoding="utf-8")

    code, report = _run(module, tmp_path, source)

    assert code == module.EXIT_BLOCKED
    assert report["status"] == "blocked"
    assert report["validation"]["error_count"] >= 1
    assert any("available_at_before_published_at" in item for item in report["validation"]["errors"])


def test_revision_chain_without_predecessor_is_blocked(tmp_path: Path) -> None:
    module = _module()
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(_record(module, revision="r2", supersedes="missing")) + "\n", encoding="utf-8")

    code, report = _run(module, tmp_path, source)

    assert code == module.EXIT_BLOCKED
    assert any("revision_predecessor_missing" in item for item in report["validation"]["errors"])


def test_csv_and_parquet_inputs_share_the_same_contract(tmp_path: Path) -> None:
    module = _module()
    row = _record(module)
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(",".join(row.keys()) + "\n" + ",".join(str(row[key]) for key in row) + "\n", encoding="utf-8")
    code, report = _run(module, tmp_path / "csv", csv_path)
    assert code == module.EXIT_READY
    assert report["row_count"] == 1

    import pyarrow as pa
    import pyarrow.parquet as pq

    parquet_dir = tmp_path / "parquet"
    parquet_dir.mkdir()
    parquet_path = parquet_dir / "rows.parquet"
    pq.write_table(pa.Table.from_pylist([row]), parquet_path)
    code, report = _run(module, parquet_dir, parquet_path)
    assert code == module.EXIT_READY
    assert report["row_count"] == 1


def test_normalized_hash_mismatch_never_becomes_ready(tmp_path: Path) -> None:
    module = _module()
    row = _record(module)
    row["normalized_record_hash"] = "b" * 64
    source = tmp_path / "rows.jsonl"
    source.write_text(json.dumps(row) + "\n", encoding="utf-8")

    code, report = _run(module, tmp_path, source)

    assert code == module.EXIT_BLOCKED
    assert any("normalized_record_hash_mismatch" in item for item in report["validation"]["errors"])
