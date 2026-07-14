from __future__ import annotations

from typing import Any

from investment_research.service.run_bundle_manifest_service import RunBundleManifestService
from investment_research.service.run_bundle_models import RunBundleManifestJudgeReport
from investment_research.service.run_bundle_models import RunBundleManifestRegistry
from investment_research.service.run_bundle_models import RunBundleMissionPackage
from investment_research.service.run_bundle_models import RunBundleOnboardingProtocol
from investment_research.service.run_bundle_models import RunBundleRegistryFailureAttribution
from investment_research.service.run_bundle_models import RunBundleRegistryManifest
from investment_research.service.run_bundle_models import RunBundleRegistryResourceRecord
from investment_research.service.run_bundle_models import RunBundleRegistrySourceContext
from investment_research.service.run_bundle_models import RunBundleRetentionCleanupPlan
from investment_research.service.run_bundle_store import RunBundleFileStore


class RunBundleRegistryService:
    """Typed access to the registry resources referenced by a run manifest."""

    def __init__(self, store: RunBundleFileStore, manifests: RunBundleManifestService) -> None:
        self.store = store
        self.manifests = manifests

    def get_registry_manifest(self, run_id: str) -> RunBundleRegistryManifest:
        manifest = self.manifests.get_manifest(run_id)
        registry = manifest.run.bundle.registry
        resource_manifest_path = registry.resourceManifestPath if registry else None
        if not resource_manifest_path:
            raise FileNotFoundError(f"Run registry manifest not found for {run_id}")
        return self.store.read_model_json(self.store.safe_run_file(run_id, resource_manifest_path), RunBundleRegistryManifest)

    def get_registry_resource(self, run_id: str, resource_name: str) -> Any:
        manifest = self.manifests.get_manifest(run_id)
        registry = manifest.run.bundle.registry
        if registry is None:
            raise FileNotFoundError(f"Run registry manifest not found for {run_id}")
        resource_path = self._resolve_registry_resource_path(run_id, registry, resource_name)
        if resource_name == "onboarding":
            return self.store.read_model_json(resource_path, RunBundleOnboardingProtocol)
        if resource_name == "mission-package":
            return self.store.read_model_json(resource_path, RunBundleMissionPackage)
        if resource_name == "judge-report":
            return self.store.read_model_json(resource_path, RunBundleManifestJudgeReport)
        if resource_name == "source-contexts":
            return self.store.read_model_json(resource_path, list[RunBundleRegistrySourceContext])
        if resource_name == "failure-attributions":
            return self.store.read_model_json(resource_path, list[RunBundleRegistryFailureAttribution])
        if resource_name == "retention-cleanup-plan":
            return self.store.read_model_json(resource_path, RunBundleRetentionCleanupPlan)
        return self.store.read_model_json(resource_path, list[RunBundleRegistryResourceRecord])

    def _resolve_registry_resource_path(
        self,
        run_id: str,
        registry: RunBundleManifestRegistry,
        resource_name: str,
    ):
        registry_paths = {
            "onboarding": registry.onboardingProtocolPath,
            "mission-package": registry.missionPackagePath,
            "selector-maps": registry.selectorMapsPath,
            "fixtures": registry.fixturesPath,
            "scenarios": registry.scenariosPath,
            "oracles": registry.oraclesPath,
            "artifacts": registry.artifactsPath,
            "evidence": registry.evidencePath,
            "judge-report": registry.judgeReportPath,
            "source-contexts": registry.sourceContextsPath,
            "failure-attributions": registry.failureAttributionsPath,
            "retention-cleanup-plan": registry.retentionCleanupPlanPath,
        }
        resource_path = registry_paths.get(resource_name)
        if not isinstance(resource_path, str) or not resource_path:
            raise FileNotFoundError(f"Registry resource not found for {run_id}: {resource_name}")
        return self.store.safe_run_file(run_id, resource_path)
