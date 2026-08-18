#!/usr/bin/env python3
"""Check the active research snapshot before a training job starts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from investment_research.training.snapshot_landing import (
    SnapshotGateConfig,
    evaluate_snapshot_gate,
    load_active_manifest,
    load_pit_leakage_audit,
    validate_landing_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("var/cn-research"))
    parser.add_argument(
        "--pit-leakage-errors", type=int, default=None,
        help="explicit count override; still requires --pit-leakage-audit",
    )
    parser.add_argument(
        "--pit-leakage-audit", type=Path, default=None,
        help="PIT leakage report used to prove the explicit count",
    )
    parser.add_argument("--labels-mature", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--minimum-market-coverage", type=float, default=0.99)
    parser.add_argument("--minimum-industry-coverage", type=float, default=0.98)
    parser.add_argument("--long-term-config", type=Path, default=None)
    args = parser.parse_args()
    try:
        manifest = load_active_manifest(args.data_root)
        snapshot_root = Path(manifest.source_root)
        integrity_errors = validate_landing_manifest(snapshot_root, manifest.model_copy(update={"source_kind": "landing", "status": "validated"}))
        gate_config = SnapshotGateConfig(
            minimum_market_coverage=args.minimum_market_coverage,
            minimum_industry_coverage=args.minimum_industry_coverage,
        )
        if args.long_term_config:
            from investment_research.training.long_term_config import load_long_term_training_config

            contract = load_long_term_training_config(args.long_term_config)
            gate_config = gate_config.model_copy(update={
                "required_datasets": set(contract.required_snapshot_datasets),
                "minimum_financial_coverage": contract.minimum_financial_coverage,
            })
        leakage_ref = None
        leakage_sha256 = None
        leakage_count = args.pit_leakage_errors
        if args.pit_leakage_audit is not None:
            leakage_count, leakage_ref, leakage_sha256 = load_pit_leakage_audit(args.pit_leakage_audit)
        result = evaluate_snapshot_gate(
            manifest,
            config=gate_config,
            pit_leakage_errors=leakage_count,
            pit_leakage_audit_ref=leakage_ref,
            pit_leakage_audit_sha256=leakage_sha256,
            labels_mature=args.labels_mature,
        )
        if integrity_errors:
            result = result.model_copy(update={
                "passed": False,
                "reasons": sorted(set([*result.reasons, *[f"integrity:{item}" for item in integrity_errors]])),
            })
        print(result.model_dump_json(indent=2))
        return 0 if result.passed else 2
    except ValueError as exc:
        print(json.dumps({"passed": False, "reasons": [str(exc)]}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
