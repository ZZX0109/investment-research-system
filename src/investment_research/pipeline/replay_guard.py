from __future__ import annotations

from investment_research.pipeline.models import AnalysisBundle
from investment_research.pipeline.run_factory import AnalysisRunFactory


class FixedRunReplayError(ValueError):
    pass


class FixedRunReplayGuard:
    """Validates that reports and replay views are anchored to an immutable run snapshot."""

    def __init__(self, run_factory: AnalysisRunFactory | None = None) -> None:
        self.run_factory = run_factory or AnalysisRunFactory()

    def validate_report_bundle(self, bundle: AnalysisBundle) -> None:
        errors: list[str] = []
        if not bundle.run.input_snapshot_ref:
            errors.append("Analysis run is missing input snapshot reference")
        if not bundle.run.input_snapshot_hash:
            errors.append("Analysis run is missing input snapshot hash")
        elif bundle.run.input_snapshot_hash != self.run_factory.hash_snapshot(bundle.snapshot):
            errors.append("Analysis run snapshot hash does not match the stored snapshot")
        if bundle.snapshot.asset_snapshot is None:
            errors.append("Analysis snapshot is missing frozen asset data")
        if not bundle.snapshot.mode:
            errors.append("Analysis source metadata is missing mode")
        if not bundle.snapshot.provider or bundle.snapshot.provider == "unknown":
            errors.append("Analysis source metadata is missing provider")
        if bundle.snapshot.as_of is None:
            errors.append("Analysis source metadata is missing as-of timestamp")
        if errors:
            raise FixedRunReplayError("; ".join(errors))
