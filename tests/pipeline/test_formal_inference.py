from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4

import pytest

from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.pipeline.formal_inference import (
    FormalArtifactVerifier,
    FormalInferenceError,
    FormalInferenceService,
)
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.domain.trusted_market import MarketSnapshot
from investment_research.domain.models import PricePoint, PriceSeries
from investment_research.domain.base import Provenance
from investment_research.domain.enums import DataMode, DataSourceType
from investment_research.training.approval_reports import REQUIRED_SCOPE_REPORTS


def _write_report(root, name: str) -> str:
    payload = {
        "schema_version": "formal-approval-evidence-v1",
        "training_run_id": "run-1",
        "market": "cn",
        "decision_context": "close_confirmed",
        "task": "drawdown_20d",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "payload": {"name": name},
    }
    digest = sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / f"{name}.json").write_text(
        json.dumps({**payload, "report_hash": digest}), encoding="utf-8"
    )
    return digest


def _manifest(root) -> TaskApprovalManifest:
    hashes = {}
    for name, contents in {
        "model.bin": b"model", "scaler.bin": b"scaler", "imputer.bin": b"imputer",
        "feature_order.json": b'{"feature_order":["ret_5d"]}',
    }.items():
        (root / name).write_bytes(contents)
        hashes[name] = sha256(contents).hexdigest()
    reports = {name: _write_report(root, name) for name in REQUIRED_SCOPE_REPORTS}
    return TaskApprovalManifest(
        task="drawdown_20d", decision_context="close_confirmed", status="approved",
        deployment_ready=True, model_name="native-risk", model_version="v1", baseline_name="baseline",
        label_policy_version="labels-v1", market="cn", applicable_markets=["cn"],
        training_run_id="run-1", artifact_hashes=hashes, data_snapshot_hash="a" * 64,
        approval_evidence_hashes=reports,
        dependency_lock_hash="b" * 64, dataset_manifest_hash=reports["dataset_manifest"],
        leakage_report_hash=reports["leakage_audit"], holdout_12m_report_hash=reports["holdout_12m"],
        stress_6m_report_hash=reports["stress_6m"], ablation_report_hash=reports["ablation"],
        critical_data_coverage=0.99, holdout_12m_passed=True, stress_6m_passed=True,
        market_regime_sample_gate_passed=True, cost_gate_passed=True, shadow_run_sessions=20,
    )


def test_formal_verifier_rejects_artifact_or_report_tampering(tmp_path) -> None:
    manifest = _manifest(tmp_path)
    verifier = FormalArtifactVerifier(tmp_path)
    assert set(verifier.verify(manifest, scope_root=tmp_path)) == set(manifest.artifact_hashes)

    (tmp_path / "scaler.bin").write_bytes(b"tampered")
    with pytest.raises(FormalInferenceError, match="artifact hash mismatch"):
        verifier.verify(manifest, scope_root=tmp_path)

    (tmp_path / "scaler.bin").write_bytes(b"scaler")
    report = tmp_path / "reports" / "ablation.json"
    original_report = report.read_text(encoding="utf-8")
    report.write_text(original_report.replace("ablation", "replaced", 1), encoding="utf-8")
    with pytest.raises(FormalInferenceError, match="report hash mismatch"):
        verifier.verify(manifest, scope_root=tmp_path)

    report.write_text(original_report, encoding="utf-8")
    (tmp_path / "reports" / "cost_liquidity.json").unlink()
    with pytest.raises(FormalInferenceError, match="approval report missing: cost_liquidity"):
        verifier.verify(manifest, scope_root=tmp_path)


def test_formal_service_rejects_synthetic_snapshot_before_model_resolution(tmp_path) -> None:
    """A direct caller cannot bypass the outer forecast bundle's synthetic gate."""
    service = FormalInferenceService(release_root=tmp_path, runtimes={})
    snapshot = AnalysisSnapshot(
        asset_id="asset-1", captured_at=datetime.now(timezone.utc),
        decision_context="close_confirmed", market_snapshot_id="snapshot-1",
        market_snapshot_hash="a" * 64, synthetic_share=0.01,
    )
    with pytest.raises(FormalInferenceError, match="rejects synthetic"):
        service.predict(
            snapshot=snapshot, market="cn", decision_context="close_confirmed",
            task="drawdown_20d",
        )


def test_formal_service_requires_authoritative_passed_market_snapshot(tmp_path) -> None:
    captured_at = datetime.now(timezone.utc)
    snapshot = AnalysisSnapshot(
        asset_id="asset-1", captured_at=captured_at, decision_context="close_confirmed",
        decision_time=captured_at, feature_built_at=captured_at,
        market_snapshot_id="snapshot-1", market_snapshot_hash="a" * 64,
    )
    no_loader = FormalInferenceService(release_root=tmp_path, runtimes={})
    with pytest.raises(FormalInferenceError, match="loader is not configured"):
        no_loader.predict(snapshot=snapshot, market="cn", decision_context="close_confirmed", task="drawdown_20d")

    failed_snapshot = MarketSnapshot.model_construct(
        content_hash="a" * 64, decision_context="close_confirmed",
        decision_time=captured_at, feature_built_at=captured_at, quality_status="failed",
    )
    service = FormalInferenceService(
        release_root=tmp_path, runtimes={}, market_snapshot_loader=lambda _id: failed_snapshot,
    )
    with pytest.raises(FormalInferenceError, match="quality is not passed"):
        service.predict(snapshot=snapshot, market="cn", decision_context="close_confirmed", task="drawdown_20d")


def test_formal_service_runs_hash_verified_test_only_scope_end_to_end(tmp_path) -> None:
    """A test-only fixture exercises the same frozen-snapshot route as production."""
    scope = tmp_path / "cn" / "close_confirmed" / "drawdown_20d"
    scope.mkdir(parents=True)
    manifest = _manifest(scope)
    (scope / "task_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    captured_at = datetime(2026, 7, 14, 7, tzinfo=timezone.utc)
    asset_id = uuid4()
    provenance = Provenance(
        data_mode=DataMode.REAL, source_type=DataSourceType.REAL,
        source_name="test-only-pit-fixture", observed_at=captured_at, confidence=1,
    )
    prices = [
        PricePoint(
            asset_id=asset_id, timestamp=datetime(2026, 7, day, tzinfo=timezone.utc),
            open=100 + day, high=101 + day, low=99 + day, close=100 + day, volume=1000,
            provenance=provenance,
        )
        for day in range(1, 7)
    ]
    snapshot = AnalysisSnapshot(
        asset_id=str(asset_id), captured_at=captured_at, as_of=captured_at,
        decision_context="close_confirmed", decision_time=captured_at,
        feature_built_at=captured_at, market_snapshot_id="snapshot-1",
        market_snapshot_hash="a" * 64, event_coverage_status="confirmed_none",
        source_types=["real"], synthetic_share=0, price_series_snapshot=[
            PriceSeries(asset_id=asset_id, interval="1d", points=prices, provenance=provenance)
        ],
    )
    frozen = MarketSnapshot.model_construct(
        content_hash="a" * 64, decision_context="close_confirmed",
        decision_time=captured_at, feature_built_at=captured_at, quality_status="passed",
    )

    class Runtime:
        def predict(self, *, manifest, values):
            assert manifest.task == "drawdown_20d"
            assert len(values) == 1
            return {"threshold_probability": 0.42}

    result = FormalInferenceService(
        release_root=tmp_path, runtimes={"drawdown_20d": Runtime()},
        market_snapshot_loader=lambda _id: frozen,
    ).predict(
        snapshot=snapshot, market="cn", decision_context="close_confirmed",
        task="drawdown_20d",
    )
    assert result.values == {"threshold_probability": 0.42}
    assert result.model_status == "approved"


def test_formal_service_reads_baseline_from_isolated_artifact_root(tmp_path) -> None:
    scope = tmp_path / "cn" / "close_confirmed" / "drawdown_20d"
    baseline_root = scope / "baseline"
    baseline_root.mkdir(parents=True)
    manifest = _manifest(baseline_root)
    (scope / "baseline_task_manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    captured_at = datetime(2026, 7, 14, 7, tzinfo=timezone.utc)
    asset_id = uuid4()
    provenance = Provenance(
        data_mode=DataMode.REAL, source_type=DataSourceType.REAL,
        source_name="test-only-pit-fixture", observed_at=captured_at, confidence=1,
    )
    snapshot = AnalysisSnapshot(
        asset_id=str(asset_id), captured_at=captured_at, as_of=captured_at,
        decision_context="close_confirmed", decision_time=captured_at,
        feature_built_at=captured_at, market_snapshot_id="snapshot-1",
        market_snapshot_hash="a" * 64, event_coverage_status="confirmed_none",
        source_types=["real"], synthetic_share=0,
        price_series_snapshot=[PriceSeries(
            asset_id=asset_id, interval="1d", provenance=provenance,
            points=[PricePoint(
                asset_id=asset_id, timestamp=datetime(2026, 7, day, tzinfo=timezone.utc),
                open=100 + day, high=101 + day, low=99 + day, close=100 + day, volume=1000,
                provenance=provenance,
            ) for day in range(1, 7)],
        )],
    )
    frozen = MarketSnapshot.model_construct(
        content_hash="a" * 64, decision_context="close_confirmed",
        decision_time=captured_at, feature_built_at=captured_at, quality_status="passed",
    )

    class Runtime:
        def predict(self, *, manifest, values):
            assert manifest.model_name == "native-risk"
            return {"threshold_probability": 0.31}

    result = FormalInferenceService(
        release_root=tmp_path, runtimes={"drawdown_20d": Runtime()},
        market_snapshot_loader=lambda _id: frozen,
    ).predict(
        snapshot=snapshot, market="cn", decision_context="close_confirmed",
        task="drawdown_20d",
    )
    assert result.model_status == "fallback"
    assert result.values == {"threshold_probability": 0.31}
