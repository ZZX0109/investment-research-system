"""Fail-closed inference boundary for formally released PIT scopes.

This module deliberately does not import the legacy mixed-market inference
service. A concrete runtime is injected by deployment code after it has loaded
native, hash-verified artifacts; this prevents a hidden pickle/root-manifest
fallback from becoming a formal prediction path.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Callable, Protocol

from pydantic import BaseModel, Field

from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.domain.data_tier import DataTier
from investment_research.pipeline.model_inference import SnapshotFeatureBuilder
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.pipeline.formal_model_router import FormalModelRouter
from investment_research.domain.trusted_market import MarketSnapshot
from investment_research.training.approval_reports import REQUIRED_SCOPE_REPORTS


REQUIRED_RUNTIME_ARTIFACTS = {"model", "scaler", "imputer", "feature_order"}
REQUIRED_REPORT_HASH_FIELDS = {
    "dataset_manifest": "dataset_manifest_hash",
    "leakage_audit": "leakage_report_hash",
    "holdout_12m": "holdout_12m_report_hash",
    "stress_6m": "stress_6m_report_hash",
    "ablation": "ablation_report_hash",
}


class FormalInferenceError(RuntimeError):
    pass


class FormalTaskPrediction(BaseModel):
    task: str
    market: str
    decision_context: str
    model_name: str
    model_version: str
    values: dict[str, float] = Field(default_factory=dict)
    feature_coverage: float = Field(ge=0, le=1)
    market_snapshot_id: str
    market_snapshot_hash: str
    model_status: str = "approved"
    fallback_from: str | None = None


class FormalTaskRuntime(Protocol):
    """Native runtime adapter; implementations must not use legacy bundles."""

    def predict(
        self, *, manifest: TaskApprovalManifest, values: list[float]
    ) -> dict[str, float]:
        ...


class FormalArtifactVerifier:
    def __init__(self, release_root: Path) -> None:
        self.release_root = release_root.resolve()

    def verify(self, manifest: TaskApprovalManifest, *, scope_root: Path) -> list[str]:
        names = set(manifest.artifact_hashes)
        missing = {
            required
            for required in REQUIRED_RUNTIME_ARTIFACTS
            if not any(Path(name).stem == required for name in names)
        }
        if missing:
            raise FormalInferenceError(
                "formal artifact set incomplete: " + ", ".join(sorted(missing))
            )
        verified: list[str] = []
        for name, expected_hash in manifest.artifact_hashes.items():
            path = self._artifact_path(scope_root, name)
            if not path.is_file():
                raise FormalInferenceError(f"formal artifact is missing: {name}")
            actual_hash = sha256(path.read_bytes()).hexdigest()
            if actual_hash != expected_hash:
                raise FormalInferenceError(f"formal artifact hash mismatch: {name}")
            verified.append(name)
        self.verify_reports(manifest, scope_root=scope_root)
        return verified

    def verify_reports(self, manifest: TaskApprovalManifest, *, scope_root: Path) -> None:
        """Verify the immutable reports bundled beside a deployable scope.

        Report content has an internal hash written by the approval writer;
        recomputing it here catches a replaced report even if its filename and
        manifest field remain unchanged.
        """
        evidence_hashes = manifest.approval_evidence_hashes
        if set(evidence_hashes) != set(REQUIRED_SCOPE_REPORTS):
            raise FormalInferenceError("formal approval evidence hash set is incomplete")
        for report_name in REQUIRED_SCOPE_REPORTS:
            expected = evidence_hashes[report_name]
            path = scope_root / "reports" / f"{report_name}.json"
            if not expected or not path.is_file():
                raise FormalInferenceError(f"formal approval report missing: {report_name}")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                recorded = payload.pop("report_hash")
                canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise FormalInferenceError(f"formal approval report is invalid: {report_name}") from exc
            actual = sha256(canonical.encode()).hexdigest()
            if recorded != actual or actual != expected:
                raise FormalInferenceError(f"formal approval report hash mismatch: {report_name}")
            manifest_field = REQUIRED_REPORT_HASH_FIELDS.get(report_name)
            if manifest_field and getattr(manifest, manifest_field) != expected:
                raise FormalInferenceError(
                    f"formal approval report hash disagrees with manifest field: {report_name}"
                )

    def feature_order(
        self, manifest: TaskApprovalManifest, *, scope_root: Path
    ) -> list[str]:
        candidates = [
            name for name in manifest.artifact_hashes if Path(name).stem == "feature_order"
        ]
        if len(candidates) != 1:
            raise FormalInferenceError("formal feature order artifact is missing or ambiguous")
        path = self._artifact_path(scope_root, candidates[0])
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            order = payload["feature_order"] if isinstance(payload, dict) else payload
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise FormalInferenceError("formal feature order is unreadable") from exc
        if not isinstance(order, list) or not order or not all(isinstance(item, str) for item in order):
            raise FormalInferenceError("formal feature order is invalid")
        return order

    def _artifact_path(self, scope_root: Path, name: str) -> Path:
        # Artifact names are release-relative and may not escape their scope.
        candidate = (scope_root / name).resolve()
        if scope_root.resolve() not in candidate.parents:
            raise FormalInferenceError("formal artifact path escapes release scope")
        return candidate


class FormalInferenceService:
    """Run one exact market/context/task scope or fail closed.

    There is intentionally no cross-market/context/task fallback. The caller
    may invoke a separately approved baseline only by resolving that exact
    baseline manifest in the same scope.
    """

    def __init__(
        self,
        *,
        release_root: Path,
        runtimes: dict[str, FormalTaskRuntime],
        feature_builder: SnapshotFeatureBuilder | None = None,
        market_snapshot_loader: Callable[[str], MarketSnapshot | None] | None = None,
    ) -> None:
        self.router = FormalModelRouter(release_root)
        self.release_root = release_root
        self.runtimes = runtimes
        self.feature_builder = feature_builder or SnapshotFeatureBuilder()
        self.verifier = FormalArtifactVerifier(release_root)
        self.market_snapshot_loader = market_snapshot_loader

    def predict(
        self,
        *,
        snapshot: AnalysisSnapshot,
        market: str,
        decision_context: str,
        task: str,
    ) -> FormalTaskPrediction:
        if (
            snapshot.synthetic_ratio > 0
            or snapshot.synthetic_share > 0
            or "synthetic" in snapshot.source_types
            or "synthetic" in snapshot.data_modes
        ):
            raise FormalInferenceError(
                "formal prediction rejects synthetic frozen snapshot inputs"
            )
        if snapshot.market_snapshot_id is None or snapshot.market_snapshot_hash is None:
            raise FormalInferenceError("formal prediction requires a frozen market snapshot")
        if snapshot.decision_context != decision_context:
            raise FormalInferenceError("decision context differs from frozen snapshot")
        self._verify_frozen_market_snapshot(snapshot, decision_context=decision_context)
        try:
            manifest = self.router.resolve(
                market=market, decision_context=decision_context, task=task
            )
            return self._predict_manifest(
                snapshot=snapshot, market=market, decision_context=decision_context,
                task=task, manifest=manifest, model_status="approved", baseline=False,
            )
        except Exception as primary_error:
            try:
                baseline = self.router.resolve_baseline(
                    market=market, decision_context=decision_context, task=task
                )
                return self._predict_manifest(
                    snapshot=snapshot, market=market, decision_context=decision_context,
                    task=task, manifest=baseline, model_status="fallback",
                    fallback_from=str(primary_error), baseline=True,
                )
            except Exception as baseline_error:
                raise FormalInferenceError(
                    f"formal task abstained; primary={primary_error}; baseline={baseline_error}"
                ) from baseline_error

    def _predict_manifest(
        self,
        *,
        snapshot: AnalysisSnapshot,
        market: str,
        decision_context: str,
        task: str,
        manifest: TaskApprovalManifest,
        model_status: str,
        fallback_from: str | None = None,
        baseline: bool = False,
    ) -> FormalTaskPrediction:
        if manifest.market != market or manifest.decision_context != decision_context or manifest.task != task:
            raise FormalInferenceError("resolved manifest does not match exact formal scope")
        if manifest.data_tier != DataTier.FORMAL_PIT:
            raise FormalInferenceError("formal inference rejects a non-formal manifest")
        scope_root = self.router.artifact_root(
            market=market, decision_context=decision_context, task=task, baseline=baseline
        )
        self.verifier.verify(manifest, scope_root=scope_root)
        order = self.verifier.feature_order(manifest, scope_root=scope_root)
        vector = self.feature_builder.build(snapshot, order)
        if vector.feature_coverage < 0.98:
            raise FormalInferenceError("formal runtime feature coverage is below 98%")
        runtime = self.runtimes.get(task)
        if runtime is None:
            raise FormalInferenceError(f"formal runtime unavailable for task: {task}")
        values = runtime.predict(manifest=manifest, values=vector.values)
        return FormalTaskPrediction(
            task=task, market=market, decision_context=decision_context,
            model_name=manifest.model_name, model_version=manifest.model_version,
            values=values, feature_coverage=vector.feature_coverage,
            market_snapshot_id=str(snapshot.market_snapshot_id),
            market_snapshot_hash=snapshot.market_snapshot_hash,
            model_status=model_status, fallback_from=fallback_from,
        )

    def _verify_frozen_market_snapshot(
        self, snapshot: AnalysisSnapshot, *, decision_context: str
    ) -> None:
        """Bind formal inference to the authoritative immutable snapshot record."""
        if self.market_snapshot_loader is None:
            raise FormalInferenceError("formal market snapshot loader is not configured")
        frozen = self.market_snapshot_loader(str(snapshot.market_snapshot_id))
        if frozen is None:
            raise FormalInferenceError("frozen market snapshot is unavailable")
        if frozen.content_hash != snapshot.market_snapshot_hash:
            raise FormalInferenceError("frozen market snapshot hash mismatch")
        if frozen.data_tier != DataTier.FORMAL_PIT:
            raise FormalInferenceError("formal inference rejects a non-formal market snapshot")
        if frozen.decision_context != decision_context:
            raise FormalInferenceError("frozen market snapshot decision context mismatch")
        if snapshot.decision_time is not None and frozen.decision_time != snapshot.decision_time:
            raise FormalInferenceError("frozen market snapshot decision time mismatch")
        if snapshot.feature_built_at is not None and frozen.feature_built_at != snapshot.feature_built_at:
            raise FormalInferenceError("frozen market snapshot feature build time mismatch")
        if frozen.quality_status != "passed":
            raise FormalInferenceError("frozen market snapshot quality is not passed")
