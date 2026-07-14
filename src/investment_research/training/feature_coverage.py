from __future__ import annotations

from pydantic import BaseModel, Field


class FeatureCoverageRecord(BaseModel):
    feature_name: str
    sample_count: int
    missing_rate: float = Field(ge=0, le=1)
    non_zero_rate: float = Field(ge=0, le=1)
    markets: list[str]
    pit_available_rate: float = Field(ge=0, le=1)
    eligible: bool
    gating_reasons: list[str] = Field(default_factory=list)


def feature_coverage_report(samples, feature_order: list[str], *, minimum_coverage: float = 0.6) -> list[FeatureCoverageRecord]:
    output: list[FeatureCoverageRecord] = []
    total = len(samples)
    for feature in feature_order:
        present = [sample for sample in samples if feature in sample.features and feature not in sample.missing_features]
        non_zero = [sample for sample in present if float(sample.features.get(feature, 0.0)) != 0.0]
        pit = [sample for sample in present if sample.feature_cutoff and (sample.as_of is None or sample.as_of <= sample.feature_cutoff)]
        coverage = len(present) / total if total else 0.0
        reasons: list[str] = []
        if coverage < minimum_coverage:
            reasons.append("feature_coverage_below_gate")
        if present and not non_zero:
            reasons.append("feature_is_constant_zero")
        output.append(
            FeatureCoverageRecord(
                feature_name=feature,
                sample_count=total,
                missing_rate=1.0 - coverage,
                non_zero_rate=len(non_zero) / total if total else 0.0,
                markets=sorted({sample.market.value for sample in present}),
                pit_available_rate=len(pit) / total if total else 0.0,
                eligible=not reasons,
                gating_reasons=reasons,
            )
        )
    return output
