from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.domain.data_tier import DataTier
from investment_research.training.approval_reports import REQUIRED_SCOPE_REPORTS
from investment_research.training.formal_preflight import FORMAL_MARKETS, FormalPreflightReport


FORMAL_CONTEXTS = ("close_confirmed", "pre_open")
FORMAL_TASKS = ("drawdown_20d", "direction_1d", "direction_5d", "return_20d")


class ReleaseIndexEntry(BaseModel):
    market: str
    decision_context: str
    task: str
    manifest_path: str
    manifest_hash: str
    status: str
    deployment_ready: bool
    gating_reasons: list[str] = Field(default_factory=list)


class FormalReleaseIndex(BaseModel):
    schema_version: str = "formal-release-index-v1"
    training_run_id: str
    preflight_report_hash: str
    expected_scope_count: int = 32
    ready_scope_count: int = 0
    entries: list[ReleaseIndexEntry] = Field(default_factory=list)


def deployment_readiness_reasons(manifest: TaskApprovalManifest) -> list[str]:
    """Return every hard release failure; an empty list is the only ready state."""
    reasons: list[str] = []
    if manifest.data_tier != DataTier.FORMAL_PIT:
        reasons.append("data_tier_is_not_formal_pit")
    if manifest.status != "approved":
        reasons.append("model_not_approved")
    if manifest.leakage_error_count:
        reasons.append("pit_leakage_errors_present")
    if manifest.calibration_leakage_error_count:
        reasons.append("calibration_leakage_errors_present")
    if manifest.critical_data_coverage < 0.98:
        reasons.append("critical_data_coverage_below_98pct")
    if manifest.formal_synthetic_output_count:
        reasons.append("formal_synthetic_output_nonzero")
    if not manifest.holdout_12m_passed:
        reasons.append("holdout_12m_not_passed")
    if not manifest.stress_6m_passed:
        reasons.append("stress_6m_not_passed")
    if not manifest.market_regime_sample_gate_passed:
        reasons.append("market_regime_sample_gate_not_passed")
    if not manifest.cost_gate_passed:
        reasons.append("cost_gate_not_passed")
    if manifest.shadow_run_sessions < 20:
        reasons.append("shadow_run_below_20_sessions")
    required_hashes = {
        "dataset_manifest": manifest.dataset_manifest_hash,
        "leakage_report": manifest.leakage_report_hash,
        "holdout_12m_report": manifest.holdout_12m_report_hash,
        "stress_6m_report": manifest.stress_6m_report_hash,
        "ablation_report": manifest.ablation_report_hash,
        "data_snapshot": manifest.data_snapshot_hash,
        "dependency_lock": manifest.dependency_lock_hash,
    }
    evidence_hashes = manifest.approval_evidence_hashes
    if (
        any(not value for value in required_hashes.values())
        or not manifest.artifact_hashes
        or set(evidence_hashes) != set(REQUIRED_SCOPE_REPORTS)
        or any(not value for value in evidence_hashes.values())
    ):
        reasons.append("artifact_or_evidence_hash_incomplete")
    return reasons


def finalize_task_manifest(
    manifest: TaskApprovalManifest,
    *,
    shadow_controller,
) -> TaskApprovalManifest:
    """Derive deployment readiness from immutable evidence; callers cannot set it."""
    shadow_sessions = shadow_controller.valid_session_count(
        training_run_id=manifest.training_run_id,
        market=manifest.market,
        decision_context=manifest.decision_context,
        task=manifest.task,
    )
    staged = manifest.model_copy(
        update={"deployment_ready": False, "shadow_run_sessions": shadow_sessions}
    )
    reasons = deployment_readiness_reasons(staged)
    return staged.model_copy(
        update={
            "deployment_ready": not reasons,
            "gating_reasons": sorted(set([*staged.gating_reasons, *reasons])),
        }
    )


def materialize_blocked_release_matrix(
    root: Path,
    *,
    preflight: FormalPreflightReport,
) -> FormalReleaseIndex:
    """Create all 32 fail-closed manifests when qualified PIT data is unavailable."""
    entries: list[ReleaseIndexEntry] = []
    for market in FORMAL_MARKETS:
        market_report = next((item for item in preflight.markets if item.market == market), None)
        provider_reasons = (
            list(market_report.missing_requirements)
            if market_report is not None
            else ["market_missing_from_formal_preflight"]
        )
        for context in FORMAL_CONTEXTS:
            for task in FORMAL_TASKS:
                relative = Path(market) / context / task / "task_manifest.json"
                path = root / relative
                manifest = TaskApprovalManifest(
                    task=task,
                    decision_context=context,
                    data_tier=DataTier.FORMAL_PIT,
                    status="research_only",
                    deployment_ready=False,
                    model_name="unavailable",
                    model_version="untrained-pit-v1",
                    baseline_name="unavailable",
                    label_policy_version=(
                        "four-market-tradeable-label-v1"
                        if task == "drawdown_20d"
                        else f"four-market-{task}-label-v1"
                    ),
                    market=market,
                    applicable_markets=[market],
                    training_run_id=preflight.training_run_id,
                    dataset_manifest_hash="",
                    leakage_report_hash="",
                    holdout_12m_report_hash="",
                    stress_6m_report_hash="",
                    ablation_report_hash="",
                    gating_reasons=["formal_pit_preflight_blocked", *provider_reasons],
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                content = manifest.model_dump_json(indent=2)
                path.write_text(content, encoding="utf-8")
                entries.append(
                    ReleaseIndexEntry(
                        market=market,
                        decision_context=context,
                        task=task,
                        manifest_path=relative.as_posix(),
                        manifest_hash=sha256(content.encode()).hexdigest(),
                        # ``TaskApprovalManifest`` deliberately accepts only
                        # approved/research_only/rejected model states.  The
                        # release index is the operational view and must make
                        # an unavailable formal scope unambiguous instead of
                        # presenting it as a usable research model.
                        status="blocked",
                        deployment_ready=False,
                        gating_reasons=list(manifest.gating_reasons),
                    )
                )
    index = FormalReleaseIndex(
        training_run_id=preflight.training_run_id,
        preflight_report_hash=preflight.report_hash,
        entries=entries,
    )
    (root / "release_index.json").write_text(index.model_dump_json(indent=2), encoding="utf-8")
    return index


def load_ready_manifest(path: Path) -> TaskApprovalManifest:
    """Load an exact-scope manifest and fail closed on any publication gap."""
    manifest = TaskApprovalManifest.model_validate_json(path.read_text(encoding="utf-8"))
    reasons = deployment_readiness_reasons(manifest)
    if not manifest.deployment_ready or reasons:
        detail = ", ".join(reasons or manifest.gating_reasons or ["deployment_ready_false"])
        raise RuntimeError(f"formal task manifest is not deployable: {detail}")
    return manifest


def hash_json_payload(payload: dict[str, Any]) -> str:
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
