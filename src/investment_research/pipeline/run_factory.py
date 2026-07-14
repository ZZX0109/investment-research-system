from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from investment_research.domain.base import GenerationLink, Provenance
from investment_research.domain.models import AnalysisRun, Asset, Evidence, User
from investment_research.pipeline.models import AnalysisSnapshot


DEFAULT_ANALYSIS_MODEL_VERSION = "heuristic-trend-ensemble@2026.07.0"
DEFAULT_REASONING_STEPS = [
    "resolve_intake_sources",
    "freeze_snapshot",
    "score_prediction",
    "evaluate_risk",
    "apply_judge_gate",
    "emit_recommendation",
]


class AnalysisRunFactory:
    """Build immutable analysis-run records from frozen input snapshots."""

    def build_run(
        self,
        *,
        asset: Asset,
        user: User,
        snapshot: AnalysisSnapshot,
        evidence: list[Evidence],
        model_version: str = DEFAULT_ANALYSIS_MODEL_VERSION,
    ) -> AnalysisRun:
        run_id = uuid4()
        return AnalysisRun(
            id=run_id,
            asset_id=asset.id,
            triggered_by=user.auth_subject,
            input_snapshot_ref=f"sqlite://analysis-snapshots/{run_id}",
            input_snapshot_hash=self.hash_snapshot(snapshot),
            model_version=model_version,
            reasoning_steps=DEFAULT_REASONING_STEPS,
            data_mode=snapshot.mode,
            provider=snapshot.provider,
            as_of=snapshot.as_of,
            overrides=snapshot.overrides,
            synthetic_ratio=snapshot.synthetic_ratio,
            evidence_ids=[item.id for item in evidence],
            provenance=self._derive_provenance(asset, captured_at=snapshot.captured_at),
        )

    def hash_snapshot(self, snapshot: AnalysisSnapshot) -> str:
        snapshot_payload = snapshot.model_dump(mode="json")
        return hashlib.sha256(json.dumps(snapshot_payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _derive_provenance(self, asset: Asset, *, captured_at) -> Provenance:
        provenance = asset.provenance.model_copy(deep=True)
        provenance.observed_at = captured_at
        provenance.generation_chain = [
            *provenance.generation_chain,
            GenerationLink(step="analysis", producer="analysis_pipeline", version="1.0.0"),
        ]
        return provenance
