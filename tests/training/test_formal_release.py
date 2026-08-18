from __future__ import annotations

from datetime import datetime, timezone

import pytest

from investment_research.training.formal_preflight import (
    FormalPreflightReport,
    MarketPreflight,
    PreflightStatus,
)
from investment_research.training.formal_release import (
    deployment_readiness_reasons,
    load_ready_manifest,
    materialize_blocked_release_matrix,
)
from investment_research.training.release_matrix import validate_release_matrix


def _blocked_report() -> FormalPreflightReport:
    return FormalPreflightReport(
        training_run_id="formal-1",
        generated_at=datetime.now(timezone.utc),
        status=PreflightStatus.BLOCKED,
        markets=[
            MarketPreflight(
                market=market,
                status=PreflightStatus.BLOCKED,
                primary_provider=f"{market}-primary",
                missing_requirements=["authorization_evidence_missing"],
            )
            for market in ("cn", "us", "hk", "jp")
        ],
        report_hash="a" * 64,
    )


def test_blocked_preflight_materializes_all_32_fail_closed_scopes(tmp_path) -> None:
    index = materialize_blocked_release_matrix(tmp_path, preflight=_blocked_report())
    assert len(index.entries) == 32
    assert index.ready_scope_count == 0
    assert {entry.status for entry in index.entries} == {"blocked"}
    assert all("authorization_evidence_missing" in entry.gating_reasons for entry in index.entries)
    status = validate_release_matrix(
        tmp_path,
        markets=["cn", "us", "hk", "jp"],
        contexts=["close_confirmed", "pre_open"],
        tasks=["drawdown_20d", "direction_1d", "direction_5d", "return_20d"],
    )
    assert status.discovered_scopes == 32
    assert status.approved_scopes == 0
    assert len(status.not_ready_scopes) == 32
    manifest_path = tmp_path / "cn/close_confirmed/drawdown_20d/task_manifest.json"
    with pytest.raises(RuntimeError, match="not deployable"):
        load_ready_manifest(manifest_path)


def test_readiness_reasons_include_holdout_shadow_and_hash_gaps(tmp_path) -> None:
    materialize_blocked_release_matrix(tmp_path, preflight=_blocked_report())
    from investment_research.domain.forecasts import TaskApprovalManifest

    manifest = TaskApprovalManifest.model_validate_json(
        (tmp_path / "us/pre_open/return_20d/task_manifest.json").read_text()
    )
    reasons = deployment_readiness_reasons(manifest)
    assert "model_not_approved" in reasons
    assert "holdout_12m_not_passed" in reasons
    assert "shadow_run_below_20_sessions" in reasons
    assert "artifact_or_evidence_hash_incomplete" in reasons
