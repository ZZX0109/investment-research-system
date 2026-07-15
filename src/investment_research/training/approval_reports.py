from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.domain.data_tier import DataTier
from investment_research.domain.pit import ModelApprovalEvidence, PITDatasetManifest


REQUIRED_SCOPE_REPORTS = (
    "dataset_manifest",
    "leakage_audit",
    "fold",
    "feature_coverage",
    "ablation",
    "calibration",
    "market_industry_regime",
    "holdout_12m",
    "stress_6m",
    "cost_liquidity",
    "artifact_hash",
    "approval",
)


class FormalApprovalReportWriter:
    """Write immutable, hash-addressed approval evidence for one exact scope."""

    def __init__(self, root: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self.root = root
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def write(
        self,
        *,
        training_run_id: str,
        market: str,
        decision_context: str,
        task: str,
        reports: dict[str, dict[str, Any]],
        catalog=None,
        artifact_ref_prefix: str | None = None,
    ) -> dict[str, str]:
        missing = set(REQUIRED_SCOPE_REPORTS) - set(reports)
        if missing:
            raise ValueError("required scope reports missing: " + ", ".join(sorted(missing)))
        scope_root = self.root / training_run_id / market / decision_context / task
        scope_root.mkdir(parents=True, exist_ok=True)
        generated_at = self.clock()
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("approval report clock must return an aware datetime")
        generated_at = generated_at.astimezone(timezone.utc)
        hashes: dict[str, str] = {}
        for name in REQUIRED_SCOPE_REPORTS:
            payload = {
                "schema_version": "formal-approval-evidence-v1",
                "training_run_id": training_run_id,
                "market": market,
                "decision_context": decision_context,
                "task": task,
                "generated_at": generated_at.isoformat(),
                "payload": reports[name],
            }
            canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            digest = sha256(canonical.encode()).hexdigest()
            payload["report_hash"] = digest
            (scope_root / f"{name}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            hashes[name] = digest
            if catalog is not None:
                reference = (
                    f"{artifact_ref_prefix.rstrip('/')}/{name}.json"
                    if artifact_ref_prefix
                    else (scope_root / f"{name}.json").resolve().as_uri()
                )
                catalog.add_approval_evidence(ModelApprovalEvidence(
                    training_run_id=training_run_id,
                    market=market,
                    decision_context=decision_context,
                    task=task,
                    evidence_type=name,
                    artifact_ref=reference,
                    artifact_hash=digest,
                    created_at=generated_at,
                ))
        return hashes

    @staticmethod
    def draft_manifest(
        *,
        dataset: PITDatasetManifest,
        report_hashes: dict[str, str],
        model_name: str,
        model_version: str,
        baseline_name: str,
        artifact_hashes: dict[str, str],
        calibration_method: str | None,
        metrics_passed: dict[str, bool],
        critical_data_coverage: float,
        formal_synthetic_output_count: int,
    ) -> TaskApprovalManifest:
        missing = set(REQUIRED_SCOPE_REPORTS) - set(report_hashes)
        if missing:
            raise ValueError("cannot draft approval manifest without all report hashes")
        return TaskApprovalManifest(
            task=dataset.task,
            decision_context=dataset.decision_context,
            data_tier=dataset.data_tier,
            # A complete evidence set is necessary but not sufficient: public
            # backfills may be evaluated here, yet are permanently
            # research-only until rebuilt from qualified formal PIT inputs.
            status=(
                "approved"
                if dataset.data_tier == DataTier.FORMAL_PIT and all(metrics_passed.values())
                else "research_only"
            ),
            deployment_ready=False,
            model_name=model_name,
            model_version=model_version,
            baseline_name=baseline_name,
            label_policy_version=dataset.label_version,
            feature_contract_version=dataset.feature_version,
            artifact_hashes=artifact_hashes,
            approval_evidence_hashes=report_hashes,
            data_snapshot_hash=dataset.dataset_hash,
            dependency_lock_hash=report_hashes["artifact_hash"],
            market=dataset.market,
            applicable_markets=[dataset.market],
            training_run_id=dataset.training_run_id,
            dataset_manifest_hash=report_hashes["dataset_manifest"],
            leakage_report_hash=report_hashes["leakage_audit"],
            holdout_12m_report_hash=report_hashes["holdout_12m"],
            stress_6m_report_hash=report_hashes["stress_6m"],
            ablation_report_hash=report_hashes["ablation"],
            calibration_method=calibration_method,
            critical_data_coverage=critical_data_coverage,
            formal_synthetic_output_count=formal_synthetic_output_count,
            leakage_error_count=int(not metrics_passed.get("pit_leakage", False)),
            calibration_leakage_error_count=int(not metrics_passed.get("calibration", False)),
            holdout_12m_passed=metrics_passed.get("holdout_12m", False),
            stress_6m_passed=metrics_passed.get("stress_6m", False),
            market_regime_sample_gate_passed=metrics_passed.get("market_regime", False),
            cost_gate_passed=metrics_passed.get("cost_liquidity", False),
            gating_reasons=[
                f"gate_failed:{name}"
                for name, passed in sorted(metrics_passed.items())
                if not passed
            ],
        )
