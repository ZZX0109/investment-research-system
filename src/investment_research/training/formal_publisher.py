from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil

from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.training.approval_reports import REQUIRED_SCOPE_REPORTS
from investment_research.training.formal_release import finalize_task_manifest


class FormalPublicationError(RuntimeError):
    pass


class FormalScopePublisher:
    """Package one exact scope without permitting caller-controlled readiness."""

    def __init__(self, release_root: Path, *, shadow_controller) -> None:
        self.release_root = release_root
        self.shadow_controller = shadow_controller

    def publish(
        self,
        *,
        manifest: TaskApprovalManifest,
        artifact_sources: dict[str, Path],
        report_sources: dict[str, Path],
        baseline: bool = False,
    ) -> TaskApprovalManifest:
        scope = self.release_root / manifest.market / manifest.decision_context / manifest.task
        scope.mkdir(parents=True, exist_ok=True)
        # A fallback has its own immutable artifact/report namespace. Keeping
        # it beside (rather than inside) the primary manifest means a later
        # baseline publication can never replace the primary model, scaler or
        # approval evidence for the same market/context/task scope.
        content_root = scope / "baseline" if baseline else scope
        self._copy_artifacts(content_root, manifest, artifact_sources)
        self._copy_reports(content_root, manifest, report_sources)
        # A serialized input can never force readiness: only immutable shadow
        # evidence plus the rest of release gates determine this field.
        staged = manifest.model_copy(update={"deployment_ready": False})
        final = finalize_task_manifest(staged, shadow_controller=self.shadow_controller)
        target = scope / ("baseline_task_manifest.json" if baseline else "task_manifest.json")
        target.write_text(final.model_dump_json(indent=2), encoding="utf-8")
        return final

    def _copy_artifacts(
        self, scope: Path, manifest: TaskApprovalManifest, sources: dict[str, Path]
    ) -> None:
        if set(sources) != set(manifest.artifact_hashes):
            raise FormalPublicationError("artifact source set differs from manifest hash set")
        for relative, expected_hash in manifest.artifact_hashes.items():
            source = sources[relative]
            if not source.is_file():
                raise FormalPublicationError(f"artifact source missing: {relative}")
            if sha256(source.read_bytes()).hexdigest() != expected_hash:
                raise FormalPublicationError(f"artifact source hash mismatch: {relative}")
            destination = (scope / relative).resolve()
            if scope.resolve() not in destination.parents:
                raise FormalPublicationError("artifact path escapes scope")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)

    def _copy_reports(
        self, scope: Path, manifest: TaskApprovalManifest, sources: dict[str, Path]
    ) -> None:
        expected = manifest.approval_evidence_hashes
        if set(expected) != set(REQUIRED_SCOPE_REPORTS):
            raise FormalPublicationError("manifest approval evidence is incomplete")
        if set(sources) != set(REQUIRED_SCOPE_REPORTS):
            raise FormalPublicationError("approval report source set is incomplete")
        # The legacy convenience fields are deliberately cross-checked here:
        # a manifest must not point at one dataset/leakage report in its top
        # level fields and ship different evidence in its immutable map.
        aliases = {
            "dataset_manifest": manifest.dataset_manifest_hash,
            "leakage_audit": manifest.leakage_report_hash,
            "holdout_12m": manifest.holdout_12m_report_hash,
            "stress_6m": manifest.stress_6m_report_hash,
            "ablation": manifest.ablation_report_hash,
        }
        if any(expected[name] != value for name, value in aliases.items()):
            raise FormalPublicationError("manifest report hash aliases are inconsistent")
        report_root = scope / "reports"
        report_root.mkdir(exist_ok=True)
        for name in REQUIRED_SCOPE_REPORTS:
            expected_hash = expected[name]
            source = sources[name]
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
                recorded = payload.pop("report_hash")
                actual = sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise FormalPublicationError(f"invalid approval report: {name}") from exc
            if actual != expected_hash or recorded != actual:
                raise FormalPublicationError(f"approval report hash mismatch: {name}")
            if (
                payload.get("training_run_id") != manifest.training_run_id
                or payload.get("market") != manifest.market
                or payload.get("decision_context") != manifest.decision_context
                or payload.get("task") != manifest.task
            ):
                raise FormalPublicationError(f"approval report scope mismatch: {name}")
            shutil.copyfile(source, report_root / f"{name}.json")
