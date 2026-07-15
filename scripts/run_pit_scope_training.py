#!/usr/bin/env python3
"""Train exact PIT release scopes from catalog manifests, never legacy pickle data.

The executable intentionally requires a catalog-native training executor. It is
separate from run_retraining.py so a formal run cannot silently consume
output/bundle_*.pkl or temp/all_samples.pkl.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from investment_research.training.approval_reports import (
    REQUIRED_SCOPE_REPORTS,
    FormalApprovalReportWriter,
)
from investment_research.training.formal_direction_runner import FormalDirectionTrainingRunner
from investment_research.training.formal_return_runner import FormalReturnTrainingRunner
from investment_research.training.formal_risk_runner import FormalRiskTrainingRunner
from investment_research.training.formal_training import FinalHoldoutLedger, candidates_for_task
from investment_research.training.formal_training import FormalScopeTrainingPlan
from investment_research.training.catalog_runtime import open_formal_catalog
from investment_research.training.pipeline_config import load_training_pipeline_config
from investment_research.domain.pit import ModelApprovalEvidence


TASKS = ("drawdown_20d", "direction_1d", "direction_5d", "return_20d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run formal PIT scope training")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--object-store-root", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_training_pipeline_config(args.config)
    run_root = args.run_root.resolve()
    training_run_id = os.environ.get("INVESTMENT_RESEARCH_TRAINING_RUN_ID")
    if not training_run_id:
        raise SystemExit("INVESTMENT_RESEARCH_TRAINING_RUN_ID is required for formal training")
    blocked: list[dict] = []
    plans: list[dict] = []
    forbidden = [PROJECT / "temp/all_samples.pkl", *sorted((PROJECT / "output").glob("bundle_*.pkl"))]
    for market in config.markets:
        catalog_ref = config.providers[market].catalog_ref
        if not catalog_ref:
            blocked.append({"market": market, "reason": "pit_catalog_ref_missing"})
            continue
        for context in config.decision_contexts:
            for task in TASKS:
                plans.append(
                    {
                        "scope": f"{market}:{context}:{task}",
                        "catalog_ref": catalog_ref,
                        "candidates": list(candidates_for_task(task)),
                        "holdout_sessions": 252,
                        "stress_sessions": 126,
                        "embargo_sessions": _horizon(task),
                        "legacy_inputs_forbidden": [str(path) for path in forbidden],
                    }
                )
    report = {
        "schema_version": "formal-scope-training-plan-v1",
        "training_run_id": training_run_id,
        "plans": plans,
        "blocked": blocked,
        "legacy_pickle_read_count": 0,
    }
    path = run_root / "audits" / "formal_scope_training_plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if blocked:
        print(f"formal scope training blocked; see {path}", file=sys.stderr)
        return 2
    opened: dict[str, tuple[object, object]] = {}
    ledger = FinalHoldoutLedger(run_root / "audits" / "final_holdout_ledger.json")
    writer = FormalApprovalReportWriter(run_root / "approval_evidence")
    try:
        for plan in plans:
            try:
                ref = str(plan["catalog_ref"])
                if ref not in opened:
                    opened[ref] = open_formal_catalog(
                        catalog_ref=ref, local_object_store_root=args.object_store_root
                    )
                _, adapter = opened[ref]
                market, context, task = str(plan["scope"]).split(":")
                dataset = adapter.load_scope(
                    training_run_id=training_run_id, market=market,
                    decision_context=context, task=task,
                )
                samples = dataset.training_samples()
                holdout, folds, fold_hash = FormalScopeTrainingPlan(
                    samples, market=market, decision_context=context, task=task,
                    prediction_horizon_sessions=_horizon(task),
                    train_window_sessions=config.train_window_days,
                    validation_window_sessions=config.validation_window_days,
                ).build()
                result = _run_task(
                    task, samples=samples, market=market, context=context,
                    dataset_hash=dataset.manifest.dataset_hash, ledger=ledger,
                )
                result_payload = _jsonable(result)
                report_hashes = writer.write(
                    training_run_id=training_run_id, market=market,
                    decision_context=context, task=task,
                    reports=_reports_for_scope(dataset.manifest.model_dump(mode="json"), plan, result_payload),
                )
                _register_approval_evidence(
                    adapter.catalog, report_hashes=report_hashes, evidence_root=run_root / "approval_evidence",
                    training_run_id=training_run_id, market=market, context=context, task=task,
                )
                # Candidate evidence is intentionally not a deployable artifact.
                # Deployment manifests are only materialized after model artifacts
                # and shadow evidence have both been independently verified.
                plan.update({
                    "status": "candidate_evaluated",
                    "dataset_hash": dataset.manifest.dataset_hash,
                    "sample_count": len(samples),
                    "holdout_start": holdout.holdout_start.isoformat(),
                    "stress_start": holdout.stress_start.isoformat(),
                    "fold_count": len(folds), "fold_hash": fold_hash,
                    "selected_candidate": result_payload["selected_candidate"],
                    "approval_report_hashes": report_hashes,
                    "deployment_ready": False,
                    "gating_reasons": ["model_artifacts_not_persisted", "shadow_run_below_20_sessions"],
                })
            except Exception as exc:
                plan.update({
                    "status": "blocked",
                    "blocking_reason": f"scope_training_failed:{type(exc).__name__}:{exc}",
                    "deployment_ready": False,
                })
    finally:
        for uow, _ in opened.values():
            uow.close()
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if report["blocked"] or any(item.get("status") == "blocked" for item in plans):
        print(f"formal scope training blocked; see {path}", file=sys.stderr)
        return 2
    return 0


def _horizon(task: str) -> int:
    return {"drawdown_20d": 20, "direction_1d": 1, "direction_5d": 5, "return_20d": 20}[task]


def _run_task(task, *, samples, market, context, dataset_hash, ledger):
    if task == "drawdown_20d":
        return FormalRiskTrainingRunner().run(
            samples=samples, market=market, decision_context=context,
            dataset_hash=dataset_hash, holdout_ledger=ledger,
        )
    if task in {"direction_1d", "direction_5d"}:
        return FormalDirectionTrainingRunner().run(
            samples=samples, market=market, decision_context=context,
            horizon=_horizon(task), dataset_hash=dataset_hash, holdout_ledger=ledger,
        )
    return FormalReturnTrainingRunner().run(
        samples=samples, market=market, decision_context=context,
        dataset_hash=dataset_hash, holdout_ledger=ledger,
    )


def _reports_for_scope(dataset_manifest, plan, result):
    candidates = result.get("candidates", [])
    selected = result.get("selected_candidate")
    selected_payload = next((item for item in candidates if item.get("name") == selected), {})
    common = {"dataset_manifest": dataset_manifest, "training_result": result}
    reports = {
        "dataset_manifest": dataset_manifest,
        "leakage_audit": {"status": "catalog_verified", "dataset_hash": dataset_manifest["dataset_hash"]},
        "fold": {"fold_hash": result["fold_hash"], "candidate_count": len(candidates)},
        "feature_coverage": {"status": "from_pit_dataset_manifest", "row_count": dataset_manifest["row_count"]},
        "ablation": {"status": "pending_formal_feature_group_execution", **common},
        "calibration": {"status": "time_oof_only", "selected": selected_payload},
        "market_industry_regime": {"status": "pending_group_evaluation", **common},
        "holdout_12m": {"status": "evaluated_once", "selected": selected, "result": result},
        "stress_6m": {"status": "pending_stress_slice_aggregation", "selected": selected},
        "cost_liquidity": {"status": "pending_authorized_market_rules"},
        "artifact_hash": {"candidate_result_hash": _hash(result), "deployable_artifacts_persisted": False},
        "approval": {"status": "research_only", "reason": "candidate_evidence_only"},
    }
    return {name: reports[name] for name in REQUIRED_SCOPE_REPORTS}


def _jsonable(value):
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _hash(value) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _register_approval_evidence(
    catalog, *, report_hashes, evidence_root, training_run_id, market, context, task
):
    for evidence_type, artifact_hash in report_hashes.items():
        catalog.add_approval_evidence(
            ModelApprovalEvidence(
                training_run_id=training_run_id,
                market=market,
                decision_context=context,
                task=task,
                evidence_type=evidence_type,
                artifact_ref=str(
                    evidence_root / training_run_id / market / context / task / f"{evidence_type}.json"
                ),
                artifact_hash=artifact_hash,
                created_at=datetime.now(timezone.utc),
            )
        )


if __name__ == "__main__":
    raise SystemExit(main())
