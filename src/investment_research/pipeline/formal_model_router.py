from __future__ import annotations

from pathlib import Path

from investment_research.domain.forecasts import TaskApprovalManifest
from investment_research.training.formal_release import load_ready_manifest


class FormalModelRouter:
    """Resolve only exact market/context/task releases; never fall back cross-scope."""

    def __init__(self, release_root: Path) -> None:
        self.release_root = release_root

    def manifest_path(self, *, market: str, decision_context: str, task: str) -> Path:
        return self.release_root / market / decision_context / task / "task_manifest.json"

    def baseline_manifest_path(self, *, market: str, decision_context: str, task: str) -> Path:
        return self.release_root / market / decision_context / task / "baseline_task_manifest.json"

    def artifact_root(
        self, *, market: str, decision_context: str, task: str, baseline: bool = False
    ) -> Path:
        root = self.manifest_path(
            market=market, decision_context=decision_context, task=task
        ).parent
        return root / "baseline" if baseline else root

    def resolve(self, *, market: str, decision_context: str, task: str) -> TaskApprovalManifest:
        path = self.manifest_path(
            market=market, decision_context=decision_context, task=task
        )
        if not path.is_file():
            raise RuntimeError(
                f"formal model unavailable for {market}:{decision_context}:{task}"
            )
        return load_ready_manifest(path)

    def resolve_baseline(
        self, *, market: str, decision_context: str, task: str
    ) -> TaskApprovalManifest:
        path = self.baseline_manifest_path(
            market=market, decision_context=decision_context, task=task
        )
        if not path.is_file():
            raise RuntimeError(
                f"formal baseline unavailable for {market}:{decision_context}:{task}"
            )
        manifest = load_ready_manifest(path)
        if (manifest.market, manifest.decision_context, manifest.task) != (
            market, decision_context, task
        ):
            raise RuntimeError("formal baseline manifest scope mismatch")
        return manifest
