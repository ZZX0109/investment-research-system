#!/usr/bin/env python3
"""One-time upgrade for pre-identity artifacts from a verified training run."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    results_path = ROOT / "output" / "results.json"
    results = _read(results_path)
    identity = {
        "training_run_id": results.get("run_label"),
        "sample_snapshot_hash": results.get("sample_snapshot_hash"),
        "feature_contract_version": results.get("feature_contract_version"),
        "data_version": results.get("data_source"),
    }
    if not all(identity.values()):
        raise RuntimeError("Authoritative results identity is incomplete")
    paths = [
        ROOT / "output" / "evaluation.json",
        ROOT / "audits" / "data_coverage.json",
        ROOT / "audits" / "label_coverage.json",
        ROOT / "audits" / "pit_audit.json",
        ROOT / "audits" / "regime_breakdown.json",
    ]
    for path in paths:
        payload = _read(path)
        existing = {key: payload.get(key) for key in identity if payload.get(key) is not None}
        for key, value in existing.items():
            expected = identity[key]
            if key == "data_version" and payload.get("data_source") is not None:
                expected = payload["data_source"]
            if value != expected:
                raise RuntimeError(f"Refusing to stamp conflicting identity in {path.name}: {key}")
        if payload.get("feature_contract_version") not in {None, identity["feature_contract_version"]}:
            raise RuntimeError(f"Feature contract mismatch in {path.name}")
        payload.update(identity)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Stamped {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
