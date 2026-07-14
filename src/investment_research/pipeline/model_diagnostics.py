"""Runtime diagnostics for keeping deployment inference inside its training contract."""

from __future__ import annotations

import math
from pathlib import Path

from pydantic import BaseModel, Field



class ModelDiagnostics(BaseModel):
    feature_coverage: float = Field(ge=0.0, le=1.0)
    out_of_range_features: list[str] = Field(default_factory=list)
    drift_score: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class ModelDiagnosticsService:
    """Uses saved scaler ranges as a deterministic, explainable drift baseline."""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir

    def evaluate(self, vector: object) -> ModelDiagnostics:
        params = self._params()
        out_of_range: list[str] = []
        feature_order = list(getattr(vector, "feature_order"))
        values = list(getattr(vector, "values"))
        coverage = float(getattr(vector, "feature_coverage"))
        for feature, value in zip(feature_order, values):
            bounds = params.get(feature, {})
            lower = bounds.get("min")
            upper = bounds.get("max")
            if lower is not None and value < float(lower) or upper is not None and value > float(upper):
                out_of_range.append(feature)
        drift_score = len(out_of_range) / max(1, len(feature_order))
        warnings: list[str] = []
        if coverage < 0.75:
            warnings.append("Feature coverage below deployment contract")
        if drift_score >= 0.20:
            warnings.append("Runtime features materially deviate from the training range")
        elif drift_score > 0:
            warnings.append("Some runtime features are outside the training range")
        return ModelDiagnostics(
            feature_coverage=coverage,
            out_of_range_features=out_of_range,
            drift_score=round(drift_score, 4),
            warnings=warnings,
        )

    def _params(self) -> dict[str, dict[str, float]]:
        path = self.model_dir / "scaler_params.json"
        if not path.exists():
            return {}
        import json
        raw = json.loads(path.read_text(encoding="utf-8"))
        # Supports the current scaler export and intentionally ignores unknown shapes.
        means = raw.get("means") or raw.get("mean") or {}
        scales = raw.get("scales") or raw.get("scale") or {}
        feature_order = raw.get("feature_order", [])
        if isinstance(means, list):
            means = dict(zip(feature_order, means))
        if isinstance(scales, list):
            scales = dict(zip(feature_order, scales))
        return {
            name: {"min": float(means[name]) - 4 * abs(float(scales.get(name, 0))), "max": float(means[name]) + 4 * abs(float(scales.get(name, 0)))}
            for name in means
            if math.isfinite(float(means[name]))
        }
