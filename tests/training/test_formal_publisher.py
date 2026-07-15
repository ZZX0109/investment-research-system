from __future__ import annotations

from hashlib import sha256

import pytest

from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.training.approval_reports import (
    REQUIRED_SCOPE_REPORTS,
    FormalApprovalReportWriter,
)
from investment_research.training.formal_publisher import (
    FormalPublicationError,
    FormalScopePublisher,
)


class _NoShadow:
    def valid_session_count(self, **_scope) -> int:
        return 0


def _manifest(tmp_path):
    report_root = tmp_path / "evidence"
    writer = FormalApprovalReportWriter(report_root)
    hashes = writer.write(
        training_run_id="run-1",
        market="us",
        decision_context="close_confirmed",
        task="drawdown_20d",
        reports={name: {"report": name} for name in REQUIRED_SCOPE_REPORTS},
    )
    artifact = tmp_path / "model.bin"
    artifact.write_bytes(b"immutable-model")
    manifest = TaskApprovalManifest(
        task="drawdown_20d", decision_context="close_confirmed", status="approved",
        model_name="linear", model_version="v1", baseline_name="linear",
        label_policy_version="four-market-tradeable-label-v1", market="us",
        applicable_markets=["us"], training_run_id="run-1",
        artifact_hashes={"model.bin": sha256(artifact.read_bytes()).hexdigest()},
        approval_evidence_hashes=hashes,
        dataset_manifest_hash=hashes["dataset_manifest"],
        leakage_report_hash=hashes["leakage_audit"],
        holdout_12m_report_hash=hashes["holdout_12m"],
        stress_6m_report_hash=hashes["stress_6m"],
        ablation_report_hash=hashes["ablation"],
        data_snapshot_hash="a" * 64,
        dependency_lock_hash=hashes["artifact_hash"],
        critical_data_coverage=0.99, holdout_12m_passed=True,
        stress_6m_passed=True, market_regime_sample_gate_passed=True,
        cost_gate_passed=True,
    )
    scope = report_root / "run-1/us/close_confirmed/drawdown_20d"
    return manifest, artifact, {name: scope / f"{name}.json" for name in REQUIRED_SCOPE_REPORTS}


def test_publisher_copies_every_required_scope_report(tmp_path) -> None:
    manifest, artifact, reports = _manifest(tmp_path)
    publisher = FormalScopePublisher(tmp_path / "release", shadow_controller=_NoShadow())

    final = publisher.publish(
        manifest=manifest,
        artifact_sources={"model.bin": artifact},
        report_sources=reports,
    )

    report_root = tmp_path / "release/us/close_confirmed/drawdown_20d/reports"
    assert {path.stem for path in report_root.glob("*.json")} == set(REQUIRED_SCOPE_REPORTS)
    # No shadow evidence exists, so complete reporting cannot be used to
    # bypass the final release gate.
    assert not final.deployment_ready


def test_publisher_blocks_missing_or_cross_scope_evidence(tmp_path) -> None:
    manifest, artifact, reports = _manifest(tmp_path)
    publisher = FormalScopePublisher(tmp_path / "release", shadow_controller=_NoShadow())
    incomplete = dict(reports)
    incomplete.pop("cost_liquidity")
    with pytest.raises(FormalPublicationError, match="source set is incomplete"):
        publisher.publish(
            manifest=manifest, artifact_sources={"model.bin": artifact}, report_sources=incomplete
        )

    tampered = reports["fold"]
    content = tampered.read_text(encoding="utf-8").replace('"market": "us"', '"market": "hk"')
    tampered.write_text(content, encoding="utf-8")
    with pytest.raises(FormalPublicationError, match="hash mismatch"):
        publisher.publish(
            manifest=manifest, artifact_sources={"model.bin": artifact}, report_sources=reports
        )


def test_baseline_publication_cannot_replace_primary_scope_artifacts(tmp_path) -> None:
    primary, primary_artifact, primary_reports = _manifest(tmp_path / "primary")
    baseline, baseline_artifact, baseline_reports = _manifest(tmp_path / "baseline")
    baseline_artifact.write_bytes(b"immutable-baseline")
    baseline = baseline.model_copy(update={
        "model_name": "baseline",
        "artifact_hashes": {"model.bin": sha256(baseline_artifact.read_bytes()).hexdigest()},
    })
    publisher = FormalScopePublisher(tmp_path / "release", shadow_controller=_NoShadow())
    publisher.publish(
        manifest=primary,
        artifact_sources={"model.bin": primary_artifact}, report_sources=primary_reports,
    )
    publisher.publish(
        manifest=baseline,
        artifact_sources={"model.bin": baseline_artifact}, report_sources=baseline_reports,
        baseline=True,
    )
    scope = tmp_path / "release/us/close_confirmed/drawdown_20d"
    assert (scope / "model.bin").read_bytes() == b"immutable-model"
    assert (scope / "baseline/model.bin").read_bytes() == b"immutable-baseline"
    assert (scope / "reports/dataset_manifest.json").is_file()
    assert (scope / "baseline/reports/dataset_manifest.json").is_file()
