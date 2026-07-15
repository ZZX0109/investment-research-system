from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from investment_research.domain.forecasts import TaskApprovalManifest


class ReleaseMatrixStatus(BaseModel):
    expected_scopes: int
    discovered_scopes: int
    approved_scopes: int
    missing_scopes: list[str] = Field(default_factory=list)
    invalid_scopes: list[str] = Field(default_factory=list)
    not_ready_scopes: list[str] = Field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.missing_scopes and not self.invalid_scopes


def validate_release_matrix(
    root: Path,
    *,
    markets: list[str],
    contexts: list[str],
    tasks: list[str],
) -> ReleaseMatrixStatus:
    expected = {f"{market}:{context}:{task}" for market in markets for context in contexts for task in tasks}
    found: dict[str, TaskApprovalManifest] = {}
    invalid: list[str] = []
    for path in root.glob("*/*/*/task_manifest.json"):
        try:
            manifest = TaskApprovalManifest.model_validate_json(path.read_text(encoding="utf-8"))
            key = f"{manifest.market}:{manifest.decision_context}:{manifest.task}"
            if key in found:
                invalid.append(f"duplicate_scope:{key}")
            found[key] = manifest
            if manifest.market not in manifest.applicable_markets:
                invalid.append(f"applicable_market_mismatch:{key}")
            if manifest.deployment_ready and manifest.status != "approved":
                invalid.append(f"deployment_status_mismatch:{key}")
            if manifest.deployment_ready and (
                manifest.shadow_run_sessions < 20
                or manifest.critical_data_coverage < 0.98
                or manifest.formal_synthetic_output_count != 0
                or manifest.leakage_error_count != 0
                or manifest.calibration_leakage_error_count != 0
                or not manifest.holdout_12m_passed
                or not manifest.stress_6m_passed
                or not manifest.market_regime_sample_gate_passed
                or not manifest.cost_gate_passed
                or not manifest.artifact_hashes
            ):
                invalid.append(f"approval_gate_incomplete:{key}")
        except Exception as exc:
            invalid.append(f"invalid_manifest:{path}:{type(exc).__name__}")
    return ReleaseMatrixStatus(
        expected_scopes=len(expected),
        discovered_scopes=len(found),
        approved_scopes=sum(
            item.status == "approved" and item.deployment_ready for item in found.values()
        ),
        missing_scopes=sorted(expected - set(found)),
        invalid_scopes=sorted(invalid),
        not_ready_scopes=sorted(
            key for key, item in found.items() if not item.deployment_ready
        ),
    )
