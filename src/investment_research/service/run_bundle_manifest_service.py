from __future__ import annotations

from pathlib import Path

from investment_research.api.artifact_security import build_run_access_token
from investment_research.api.artifact_security import build_signed_artifact_url
from investment_research.api.artifact_security import get_artifact_access_settings
from investment_research.api.artifact_security import should_sign_report_url
from investment_research.service.run_bundle_models import RunBundleComparisonReport
from investment_research.service.run_bundle_models import RunBundleHistoryEntry
from investment_research.service.run_bundle_models import RunBundleHistoryIndex
from investment_research.service.run_bundle_models import RunBundleManifest
from investment_research.service.run_bundle_models import RunBundleManifestArtifact
from investment_research.service.run_bundle_models import RunBundleManifestArtifactAccess
from investment_research.service.run_bundle_models import RunBundleManifestBundle
from investment_research.service.run_bundle_models import RunBundleManifestRegistry
from investment_research.service.run_bundle_models import RunBundleManifestRegistryResourceUrls
from investment_research.service.run_bundle_models import RunBundleManifestReportUrls
from investment_research.service.run_bundle_store import RunBundleFileStore


class RunBundleManifestService:
    """Reads and enriches run history and manifest views."""

    def __init__(self, store: RunBundleFileStore) -> None:
        self.store = store

    def get_history(self) -> RunBundleHistoryIndex:
        history_path = self.store.runs_root / "history.json"
        if not history_path.exists():
            return RunBundleHistoryIndex()
        return self.store.read_model_json(history_path, RunBundleHistoryIndex)

    def list_runs(self, *, mission_id: str | None = None) -> list[RunBundleHistoryEntry]:
        runs = self.get_history().runs
        if mission_id:
            return [run for run in runs if run.missionId == mission_id]
        return runs

    def get_manifest(self, run_id: str) -> RunBundleManifest:
        run_dir = self.store.safe_run_root(run_id)
        manifest_path = run_dir / "manifest.json"
        if not manifest_path.exists():
            history_entry = next(
                (entry for entry in self.list_runs() if entry.runId == run_id),
                None,
            )
            if history_entry is None:
                raise FileNotFoundError(f"Run manifest not found for {run_id}")
            if not history_entry.manifestPath:
                raise FileNotFoundError(f"Run manifest path missing for {run_id}")
            manifest_path = Path(history_entry.manifestPath)
        return self._enrich_manifest(run_id, self.store.read_model_json(manifest_path, RunBundleManifest))

    def get_latest_manifest(self, *, mission_id: str | None = None) -> RunBundleManifest:
        runs = self.list_runs(mission_id=mission_id)
        if not runs:
            raise FileNotFoundError("No run history available")
        run_id = runs[0].runId
        manifest_path = runs[0].manifestPath
        if not manifest_path:
            raise FileNotFoundError(f"Run manifest path missing for {run_id}")
        return self._enrich_manifest(run_id, self.store.read_model_json(Path(manifest_path), RunBundleManifest))

    def get_comparison(self, run_id: str) -> RunBundleComparisonReport | None:
        comparison_path = self.store.safe_run_root(run_id) / "reports" / "comparison.json"
        if not comparison_path.exists():
            return None
        return self.store.read_model_json(comparison_path, RunBundleComparisonReport)

    def artifact_relative_path(self, artifact: RunBundleManifestArtifact) -> str | None:
        metadata = artifact.metadata or {}
        relative_path = metadata.get("relativePath")
        if isinstance(relative_path, str) and relative_path:
            return relative_path

        path_value = artifact.path
        if not path_value:
            return None

        try:
            path_obj = Path(path_value).resolve()
            inferred_run_id = self._infer_run_id_from_artifact_path(path_obj)
            if not inferred_run_id:
                return None
            artifacts_root = (self.store.runs_root / inferred_run_id / "artifacts").resolve()
            if artifacts_root in path_obj.parents:
                return f"artifacts/{path_obj.name}"
        except OSError:
            return None
        return None

    def _enrich_manifest(self, run_id: str, manifest: RunBundleManifest) -> RunBundleManifest:
        run_bundle = manifest.run.bundle
        access_settings = get_artifact_access_settings()
        run_token = build_run_access_token(run_id, settings=access_settings)
        enriched_bundle = run_bundle.model_copy(
            update={
                "manifestUrl": f"/api/v1/test-officer/runs/{run_id}/manifest",
                "reportUrls": self._build_report_urls(run_id, run_bundle),
                "artifactAccess": RunBundleManifestArtifactAccess(
                    tokenRequired=True,
                    header="x-test-officer-token",
                    runTokenHeader="x-test-officer-run-token",
                    runToken=run_token,
                    runTokenScope=run_id,
                    devLoopbackOnly=True,
                    signedUrlTtlSeconds=access_settings.signed_url_ttl_seconds,
                    runTokenTtlSeconds=access_settings.signed_url_ttl_seconds,
                ),
                "registry": self._enrich_registry(run_id, run_bundle.registry),
            }
        )
        return manifest.model_copy(
            update={
                "run": manifest.run.model_copy(update={"bundle": enriched_bundle}),
                "artifacts": [self._enrich_artifact(run_id, artifact) for artifact in manifest.artifacts],
            }
        )

    def _enrich_registry(
        self,
        run_id: str,
        registry: RunBundleManifestRegistry | None,
    ) -> RunBundleManifestRegistry | None:
        if registry is None:
            return None
        return registry.model_copy(
            update={
                "resourceManifestUrl": f"/api/v1/test-officer/runs/{run_id}/registry",
                "resourceUrls": RunBundleManifestRegistryResourceUrls(
                    onboardingProtocol=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/onboarding"
                        if registry.onboardingProtocolPath
                        else None
                    ),
                    missionPackage=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/mission-package"
                        if registry.missionPackagePath
                        else None
                    ),
                    selectorMaps=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/selector-maps"
                        if registry.selectorMapsPath
                        else None
                    ),
                    fixtures=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/fixtures"
                        if registry.fixturesPath
                        else None
                    ),
                    scenarios=f"/api/v1/test-officer/runs/{run_id}/registry/scenarios",
                    oracles=f"/api/v1/test-officer/runs/{run_id}/registry/oracles",
                    artifacts=f"/api/v1/test-officer/runs/{run_id}/registry/artifacts",
                    evidence=f"/api/v1/test-officer/runs/{run_id}/registry/evidence",
                    judgeReport=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/judge-report"
                        if registry.judgeReportPath
                        else None
                    ),
                    sourceContexts=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/source-contexts"
                        if registry.sourceContextsPath
                        else None
                    ),
                    failureAttributions=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/failure-attributions"
                        if registry.failureAttributionsPath
                        else None
                    ),
                    retentionCleanupPlan=(
                        f"/api/v1/test-officer/runs/{run_id}/registry/retention-cleanup-plan"
                        if registry.retentionCleanupPlanPath
                        else None
                    ),
                ),
            }
        )

    def _enrich_artifact(self, run_id: str, artifact: RunBundleManifestArtifact) -> RunBundleManifestArtifact:
        relative_path = self.artifact_relative_path(artifact)
        metadata = dict((artifact.metadata or {}).model_dump()) if hasattr(artifact.metadata, "model_dump") else dict(artifact.metadata or {})
        if relative_path:
            metadata.setdefault("relativePath", relative_path)
            metadata["artifactUrl"] = build_signed_artifact_url(
                f"/api/v1/test-officer/runs/{run_id}/artifacts/{relative_path.removeprefix('artifacts/')}"
            )
        return artifact.model_copy(update={"metadata": metadata or None})

    def _infer_run_id_from_artifact_path(self, artifact_path: Path) -> str | None:
        try:
            relative = artifact_path.relative_to(self.store.runs_root)
        except ValueError:
            return None
        if len(relative.parts) < 2:
            return None
        return relative.parts[0]

    def _build_report_urls(self, run_id: str, bundle: RunBundleManifestBundle) -> RunBundleManifestReportUrls:
        reports_dir = Path(bundle.reportsDir)
        report_names = {
            "json": "run-report.json",
            "junit": "junit.xml",
            "markdown": "report.md",
            "html": "report.html",
            "comparison": "comparison.json",
            "gate": "gate.json",
            "prAnnotation": "pr-annotation.md",
            "githubAnnotations": "pr-annotations.json",
            "ciArtifactManifest": "artifact-upload-manifest.json",
            "retentionJob": "retention-job.json",
            "integrity": "integrity-report.json",
            "downloadManifest": "download-manifest.json",
        }
        urls: dict[str, str] = {}
        for key, filename in report_names.items():
            if (reports_dir / filename).exists():
                report_url = f"/api/v1/test-officer/runs/{run_id}/reports/{filename}"
                urls[key] = build_signed_artifact_url(report_url) if should_sign_report_url(filename) else report_url
        return RunBundleManifestReportUrls.model_validate(urls)
