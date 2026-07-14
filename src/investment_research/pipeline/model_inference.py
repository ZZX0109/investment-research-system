from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from investment_research.domain.enums import EvidenceType
from investment_research.domain.models import Evidence, ModelDiagnostic, PricePoint
from investment_research.feature_contract import (
    asof_aligned_values,
    FEATURE_CONTRACT_VERSION,
    StructuredEventRecord,
    build_structured_event_features,
    count_recent_events,
    realized_volatility,
    window_return,
    zscore,
)
from investment_research.pipeline.models import AnalysisSnapshot
from investment_research.pipeline.model_diagnostics import ModelDiagnosticsService
from investment_research.pipeline.artifact_integrity import (
    ArtifactIntegrityError,
    verify_artifact_set,
)
from investment_research.training.sources import (
    infer_event_direction,
    infer_event_intensity,
    infer_event_type,
    infer_guidance_bucket,
    infer_surprise_bucket,
)


DEFAULT_MODEL_DIR = Path(__file__).resolve().parents[3] / "output" / "models"
APPROVED_STATUS = "approved"
DEFAULT_TARGET_NAME = "future_max_drawdown_20d"
MINIMUM_INFERENCE_FEATURE_COVERAGE = 0.75


class ModelInferenceError(RuntimeError):
    """Raised when the deployment model cannot produce a trusted prediction."""


class SnapshotFeatureVector(BaseModel):
    feature_order: list[str]
    values: list[float]
    feature_coverage: float = Field(ge=0.0, le=1.0)
    missing_features: list[str] = Field(default_factory=list)


class ModelInferenceResult(BaseModel):
    model_name: str
    model_version: str
    model_status: str
    deployment_approved: bool
    target_name: str = DEFAULT_TARGET_NAME
    manifest_version: str | None = None
    signal: str
    confidence: float = Field(ge=0.0, le=1.0)
    risk_probability: float = Field(ge=0.0, le=1.0)
    feature_coverage: float = Field(ge=0.0, le=1.0)
    missing_features: list[str] = Field(default_factory=list)
    inference_warnings: list[str] = Field(default_factory=list)
    diagnostic: ModelDiagnostic | None = None
    rationale: str


class SnapshotFeatureBuilder:
    """Convert frozen analysis snapshots into the tabular training feature shape."""

    def build(
        self, snapshot: AnalysisSnapshot, feature_order: list[str]
    ) -> SnapshotFeatureVector:
        values_by_name: dict[str, float] = {}
        missing: list[str] = []

        price_points = self._price_points(snapshot, role="asset")
        closes = [point.close for point in price_points]
        volumes = [
            float(point.volume) for point in price_points if point.volume is not None
        ]

        ret_5d = self._window_metric(closes, 5, "ret_5d", missing, window_return)
        ret_20d = self._window_metric(closes, 20, "ret_20d", missing, window_return)
        values_by_name["ret_5d"] = ret_5d
        values_by_name["ret_20d"] = ret_20d
        values_by_name["vol_5d"] = self._window_metric(
            closes, 5, "vol_5d", missing, realized_volatility
        )
        values_by_name["vol_20d"] = self._window_metric(
            closes, 20, "vol_20d", missing, realized_volatility
        )
        values_by_name["volume_z_20d"] = self._volume_z(volumes, missing)
        values_by_name["halted_flag"] = self._halted_flag(price_points)
        values_by_name.update(self._market_flags(snapshot))

        for role, return_feature, relative_feature in (
            ("benchmark", "benchmark_ret_20d", "relative_strength_20d"),
            ("sector", "sector_ret_20d", "sector_relative_strength_20d"),
            ("style", "style_ret_20d", "style_relative_strength_20d"),
        ):
            reference_return = self._reference_return(
                snapshot, role=role, asset_points=price_points
            )
            if reference_return is None:
                values_by_name[return_feature] = 0.0
                values_by_name[relative_feature] = 0.0
                missing.extend([return_feature, relative_feature])
            else:
                values_by_name[return_feature] = reference_return
                values_by_name[relative_feature] = ret_20d - reference_return

        as_of = snapshot.as_of or snapshot.captured_at
        evidence = snapshot.evidence_snapshot
        structured_events = self._structured_events(evidence, as_of=as_of)
        event_counts = count_recent_events(structured_events, as_of.date())
        values_by_name.update(
            {name: float(value) for name, value in event_counts.items()}
        )
        values_by_name.update(
            build_structured_event_features(structured_events, as_of.date())
        )
        if any(
            name in feature_order
            for name in (
                "turnover_percentile_20d",
                "relative_liquidity_20d",
                "market_breadth_5d",
                "industry_strength_20d",
                "limit_up_flag",
                "limit_down_flag",
                "margin_financing_change_5d",
                "announcement_regulatory_count_30d",
                "announcement_shareholder_action_count_30d",
            )
        ):
            self._add_v2_features(
                values_by_name, missing, price_points, structured_events
            )
        coverage_is_legacy_but_observed = (
            snapshot.event_coverage_status == "unknown" and bool(structured_events)
        )
        if (
            snapshot.event_coverage_status
            not in {"events_present", "confirmed_none", "complete"}
            and not coverage_is_legacy_but_observed
        ):
            for name in [
                name for name in feature_order if self._is_event_feature(name)
            ]:
                values_by_name.pop(name, None)
                missing.append(name)

        ordered_values: list[float] = []
        for name in feature_order:
            if name in values_by_name:
                ordered_values.append(float(values_by_name[name]))
            else:
                ordered_values.append(self._default_missing(name, missing))
        unique_missing = list(dict.fromkeys(missing))
        coverage = 1.0 - (len(unique_missing) / max(1, len(feature_order)))
        return SnapshotFeatureVector(
            feature_order=feature_order,
            values=ordered_values,
            feature_coverage=max(0.0, min(1.0, coverage)),
            missing_features=unique_missing,
        )

    def _add_v2_features(self, values, missing, points, events) -> None:
        if not points:
            missing.extend(
                [
                    "turnover_percentile_20d",
                    "relative_liquidity_20d",
                    "market_breadth_5d",
                    "industry_strength_20d",
                    "limit_up_flag",
                    "limit_down_flag",
                    "margin_financing_change_5d",
                ]
            )
            return
        latest = points[-1]
        turnover = [
            point.turnover_rate
            for point in points[-20:]
            if point.turnover_rate is not None
        ]
        if latest.turnover_rate is not None and turnover:
            values["turnover_percentile_20d"] = sum(
                value <= latest.turnover_rate for value in turnover
            ) / len(turnover)
        else:
            missing.append("turnover_percentile_20d")
        amounts = [
            point.amount
            for point in points[-20:]
            if point.amount is not None and point.amount > 0
        ]
        if latest.amount is not None and amounts:
            values["relative_liquidity_20d"] = latest.amount / (
                sum(amounts) / len(amounts)
            )
        else:
            missing.append("relative_liquidity_20d")
        if latest.market_breadth_5d is not None:
            values["market_breadth_5d"] = latest.market_breadth_5d
        else:
            missing.append("market_breadth_5d")
        if "sector_relative_strength_20d" in values:
            values["industry_strength_20d"] = values["sector_relative_strength_20d"]
        else:
            missing.append("industry_strength_20d")
        values["limit_up_flag"] = 1.0 if latest.is_limit_up else 0.0
        values["limit_down_flag"] = 1.0 if latest.is_limit_down else 0.0
        margin = [
            point.margin_financing_balance
            for point in points[-6:]
            if point.margin_financing_balance is not None
        ]
        if len(margin) >= 2 and margin[0] > 0:
            values["margin_financing_change_5d"] = margin[-1] / margin[0] - 1.0
        else:
            missing.append("margin_financing_change_5d")
        values["announcement_regulatory_count_30d"] = float(
            sum(
                event.event_type in {"regulation", "policy", "litigation"}
                for event in events
            )
        )
        values["announcement_shareholder_action_count_30d"] = float(
            sum(
                (event.filing_subtype or "").lower()
                in {"buyback", "shareholder_change", "insider_sale", "pledge"}
                for event in events
            )
        )

    @staticmethod
    def _is_event_feature(name: str) -> bool:
        return any(
            marker in name
            for marker in (
                "event",
                "news",
                "filing",
                "earnings",
                "guidance",
                "surprise",
                "announcement",
                "regulatory",
            )
        )

    def _price_points(
        self, snapshot: AnalysisSnapshot, *, role: str
    ) -> list[PricePoint]:
        points: list[PricePoint] = []
        for series in snapshot.price_series_snapshot:
            if series.series_role != role:
                continue
            points.extend(series.points)
        return sorted(points, key=lambda point: point.timestamp)

    def _window_metric(self, closes, window, feature_name, missing, metric) -> float:
        if len(closes) < window:
            missing.append(feature_name)
            return 0.0
        return float(metric(closes[-window:]))

    def _volume_z(self, volumes: list[float], missing: list[str]) -> float:
        if len(volumes) < 20:
            missing.append("volume_z_20d")
            return 0.0
        return zscore(volumes[-1], volumes[-20:])

    def _halted_flag(self, price_points: list[PricePoint]) -> float:
        if not price_points:
            return 0.0
        latest = price_points[-1]
        return 1.0 if latest.volume == 0 else 0.0

    def _market_flags(self, snapshot: AnalysisSnapshot) -> dict[str, float]:
        asset = snapshot.asset_snapshot
        if asset is None:
            return {f"market_{market}_flag": 0.0 for market in ("cn", "us", "hk", "jp")}
        haystack = " ".join(
            part.lower()
            for part in [asset.ticker, asset.exchange or "", asset.currency]
            if part
        )
        detected = "us"
        markers = {
            "cn": (
                ".ss",
                ".sh",
                ".sz",
                ".bj",
                "shanghai",
                "shenzhen",
                "beijing",
                "cny",
                "cnh",
                "sse",
                "szse",
                "xshg",
                "xshe",
                "xbse",
            ),
            "hk": (".hk", "hong kong", "hkd", "xhkg"),
            "jp": (".t", "tokyo", "jpy", "xtks"),
        }
        for market, candidates in markers.items():
            if any(marker in haystack for marker in candidates):
                detected = market
                break
        return {
            f"market_{market}_flag": 1.0 if market == detected else 0.0
            for market in ("cn", "us", "hk", "jp")
        }

    def _reference_return(
        self,
        snapshot: AnalysisSnapshot,
        *,
        role: str,
        asset_points: list[PricePoint],
    ) -> float | None:
        reference_points = self._price_points(snapshot, role=role)
        if len(reference_points) < 20:
            return None
        matching = asof_aligned_values(
            [(point.timestamp.date(), point.timestamp) for point in asset_points],
            [
                (point.timestamp.date(), point.timestamp, point.close)
                for point in reference_points
            ],
        )
        if len(matching) < 20:
            return None
        return window_return(matching[-20:])

    def _structured_events(
        self, evidence: list[Evidence], *, as_of: datetime
    ) -> list[StructuredEventRecord]:
        events: list[StructuredEventRecord] = []
        for item in evidence:
            published_at = item.published_at or item.collected_at
            if published_at > as_of:
                continue
            text = f"{item.title} {item.summary}".strip()
            inferred_type = infer_event_type(text).value
            if item.evidence_type == EvidenceType.NEWS:
                inferred_type = "news" if inferred_type == "news" else inferred_type
            elif item.evidence_type == EvidenceType.FILING:
                inferred_type = "filing"
            source_tier = item.source_tier or self._source_tier(
                item.provenance.source_name
            )
            filing_type = item.filing_type
            if filing_type is None:
                filing_type = next(
                    (
                        form
                        for form in ("8-K", "10-Q", "10-K")
                        if form.lower() in text.lower()
                    ),
                    None,
                )
            events.append(
                StructuredEventRecord(
                    published_at=published_at,
                    event_type=item.event_type or inferred_type,
                    event_direction=item.direction or infer_event_direction(text).value,
                    event_intensity=item.intensity or infer_event_intensity(text).value,
                    source_tier=source_tier,
                    surprise_bucket=item.surprise_bucket
                    or infer_surprise_bucket(text).value,
                    guidance_bucket=item.guidance_bucket
                    or infer_guidance_bucket(text).value,
                    filing_subtype=filing_type,
                )
            )
        return events

    def _source_tier(self, source_name: str) -> str:
        normalized = source_name.lower()
        if any(token in normalized for token in ("sec", "regulator", "监管")):
            return "regulatory"
        if any(
            token in normalized for token in ("cninfo", "hkex", "exchange", "交易所")
        ):
            return "exchange"
        if "official" in normalized or "公司公告" in normalized:
            return "official"
        if any(token in normalized for token in ("yfinance", "aggregator")):
            return "aggregator"
        return "mainstream_news"

    def _default_missing(self, feature_name: str, missing: list[str]) -> float:
        missing.append(feature_name)
        return 0.0


class DeploymentModelInferenceService:
    """Run approved deployment models against a frozen analysis snapshot."""

    def __init__(
        self,
        *,
        model_dir: Path | None = None,
        feature_builder: SnapshotFeatureBuilder | None = None,
    ) -> None:
        self.model_dir = model_dir or DEFAULT_MODEL_DIR
        self.feature_builder = feature_builder or SnapshotFeatureBuilder()
        self._loaded_model: Any | None = None
        self._loaded_model_name: str | None = None

    def predict(self, snapshot: AnalysisSnapshot) -> ModelInferenceResult:
        manifest = self._load_json(self.model_dir / "model_manifest.json")
        if not manifest.get("deployment_ready"):
            raise ModelInferenceError("Model manifest is not deployment ready")
        if manifest.get("schema_version") == "model-artifact-set-v3":
            try:
                verify_artifact_set(self.model_dir, manifest)
            except ArtifactIntegrityError as exc:
                raise ModelInferenceError(str(exc)) from exc
        if manifest.get("legacy_cutoff_semantics"):
            raise ModelInferenceError(
                "legacy_cutoff_semantics artifacts are research-only"
            )
        if (
            manifest.get("decision_context")
            and manifest.get("decision_context") != snapshot.decision_context
        ):
            raise ModelInferenceError(
                "Model decision context does not match frozen market snapshot"
            )

        feature_order = self._feature_order()
        feature_vector = self.feature_builder.build(snapshot, feature_order)
        diagnostics = ModelDiagnosticsService(self.model_dir).evaluate(feature_vector)
        minimum_coverage = self._minimum_feature_coverage()
        if feature_vector.feature_coverage < minimum_coverage:
            raise ModelInferenceError(
                "Runtime feature coverage "
                f"{feature_vector.feature_coverage:.1%} is below the "
                f"{minimum_coverage:.0%} deployment threshold"
            )
        scaled_values = self._scale(feature_vector.values)
        model_name, model_info, deployment_role, fallback_warnings = (
            self._predictable_model(
                manifest,
                scaled_values,
            )
        )
        probability = self._predict_probability(model_name, model_info, scaled_values)
        signal = self._risk_signal(probability)
        confidence = self._confidence(
            risk_probability=probability,
            feature_coverage=feature_vector.feature_coverage,
            real_share=snapshot.real_share,
        )
        manifest_version = str(manifest.get("training_generated_at") or "unknown")
        warnings = [
            *fallback_warnings,
            *self._feature_warnings(feature_vector),
            *diagnostics.warnings,
        ]

        return ModelInferenceResult(
            model_name=model_name,
            model_version=manifest_version,
            model_status=APPROVED_STATUS,
            deployment_approved=True,
            target_name=str(
                model_info.get("target_name")
                or manifest.get("target_name")
                or DEFAULT_TARGET_NAME
            ),
            manifest_version=manifest_version,
            signal=signal,
            confidence=confidence,
            risk_probability=probability,
            feature_coverage=feature_vector.feature_coverage,
            missing_features=feature_vector.missing_features,
            inference_warnings=warnings,
            diagnostic=ModelDiagnostic(
                feature_coverage=feature_vector.feature_coverage,
                missing_features=feature_vector.missing_features,
                out_of_range_features=diagnostics.out_of_range_features,
                drift_score=diagnostics.drift_score,
                provider_missing_rate=1.0 - snapshot.real_share,
                warnings=diagnostics.warnings,
            ),
            rationale=(
                f"Approved {deployment_role} deployment model estimated {probability:.1%} "
                f"{DEFAULT_TARGET_NAME} risk with {feature_vector.feature_coverage:.0%} feature coverage "
                f"under {FEATURE_CONTRACT_VERSION}; drift score={diagnostics.drift_score:.0%}."
            ),
        )

    def predict_comparison(self, snapshot: AnalysisSnapshot) -> dict[str, float | None]:
        """Evaluate approved primary/fallback plus a deterministic volatility baseline."""
        manifest = self._load_json(self.model_dir / "model_manifest.json")
        feature_vector = self.feature_builder.build(snapshot, self._feature_order())
        if feature_vector.feature_coverage < self._minimum_feature_coverage():
            return {
                "primary": None,
                "champion_fallback": None,
                "trailing_volatility_heuristic": None,
            }
        scaled = self._scale(feature_vector.values)
        values: dict[str, float | None] = {}
        for role, model_name in self._deployment_model_candidates(manifest):
            model_info = dict(manifest.get("models", {}).get(model_name) or {})
            try:
                values[role] = self._predict_probability(model_name, model_info, scaled)
            except ModelInferenceError:
                values[role] = None
        feature_names = feature_vector.feature_order
        vol_index = (
            feature_names.index("vol_20d") if "vol_20d" in feature_names else None
        )
        if vol_index is None or "vol_20d" in feature_vector.missing_features:
            values["trailing_volatility_heuristic"] = None
        else:
            # Maps realized daily volatility to a bounded warning score without claiming calibration.
            raw_volatility = max(0.0, feature_vector.values[vol_index])
            values["trailing_volatility_heuristic"] = min(1.0, raw_volatility / 0.04)
        return values

    def snapshot_feature_vector(
        self, snapshot: AnalysisSnapshot
    ) -> SnapshotFeatureVector:
        return self.feature_builder.build(snapshot, self._feature_order())

    def _approved_model_name(self, manifest: dict[str, Any]) -> str:
        approved = [str(name) for name in manifest.get("approved_trainers", []) if name]
        if not approved:
            raise ModelInferenceError("No approved model is listed in manifest")
        return approved[0]

    def _predictable_model(
        self,
        manifest: dict[str, Any],
        scaled_values: list[float],
    ) -> tuple[str, dict[str, Any], str, list[str]]:
        warnings: list[str] = []
        last_error: Exception | None = None
        for deployment_role, model_name in self._deployment_model_candidates(manifest):
            model_info = dict(manifest.get("models", {}).get(model_name) or {})
            if model_info.get("status") != APPROVED_STATUS:
                last_error = ModelInferenceError(
                    f"Model {model_name} is not marked approved in manifest"
                )
                warnings.append(
                    f"{deployment_role} model {model_name} skipped: {last_error}"
                )
                continue
            try:
                self._predict_probability(model_name, model_info, scaled_values)
                return model_name, model_info, deployment_role, warnings
            except ModelInferenceError as exc:
                last_error = exc
                warnings.append(
                    f"{deployment_role} model {model_name} unavailable: {exc}"
                )
                self._loaded_model = None
                self._loaded_model_name = None
        if last_error is not None:
            raise ModelInferenceError(
                f"No deployable approved model could be loaded: {last_error}"
            ) from last_error
        raise ModelInferenceError("No approved model is listed in manifest")

    def _deployment_model_candidates(
        self, manifest: dict[str, Any]
    ) -> list[tuple[str, str]]:
        candidates: list[tuple[str, str]] = []
        primary = manifest.get("primary_model")
        if isinstance(primary, dict) and primary.get("trainer_name"):
            candidates.append(("primary", str(primary["trainer_name"])))
        fallback = manifest.get("champion_fallback")
        if isinstance(fallback, dict) and fallback.get("trainer_name"):
            candidates.append(("champion_fallback", str(fallback["trainer_name"])))
        if not candidates:
            candidates.append(("approved", self._approved_model_name(manifest)))

        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for role, name in candidates:
            if name in seen:
                continue
            seen.add(name)
            deduped.append((role, name))
        return deduped

    def _feature_order(self) -> list[str]:
        metadata = self._load_json(self.model_dir / "feature_order.json")
        feature_order = metadata.get("feature_order")
        if not isinstance(feature_order, list) or not feature_order:
            raise ModelInferenceError("Feature metadata is missing feature_order")
        return [str(name) for name in feature_order]

    def _minimum_feature_coverage(self) -> float:
        metadata = self._load_json(self.model_dir / "feature_order.json")
        configured = float(
            metadata.get(
                "minimum_inference_feature_coverage", MINIMUM_INFERENCE_FEATURE_COVERAGE
            )
        )
        return max(0.0, min(1.0, configured))

    def _scale(self, values: list[float]) -> list[float]:
        params = self._load_json(self.model_dir / "scaler_params.json")
        means = params.get("mean")
        scales = params.get("scale")
        if not isinstance(means, list) or not isinstance(scales, list):
            raise ModelInferenceError("Scaler metadata is missing mean/scale")
        if len(means) != len(values) or len(scales) != len(values):
            raise ModelInferenceError(
                "Scaler metadata length does not match feature vector"
            )
        scaled: list[float] = []
        for value, mu, sigma in zip(values, means, scales):
            scale = float(sigma) if float(sigma) != 0.0 else 1.0
            scaled.append((float(value) - float(mu)) / scale)
        return scaled

    def _predict_probability(
        self, model_name: str, model_info: dict[str, Any], scaled_values: list[float]
    ) -> float:
        model = self._load_model(model_name, model_info)
        row = [scaled_values]
        if hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(row)
            classes = list(getattr(model, "classes_", []))
            positive_index = (
                classes.index(1) if 1 in classes else len(probabilities[0]) - 1
            )
            return self._clean_probability(float(probabilities[0][positive_index]))
        if hasattr(model, "decision_function"):
            score = float(model.decision_function(row)[0])
            return self._clean_probability(1.0 / (1.0 + math.exp(-score)))
        if hasattr(model, "predict"):
            return self._clean_probability(float(model.predict(row)[0]))
        raise ModelInferenceError(
            f"Model {model_name} does not expose a supported prediction method"
        )

    def _load_model(self, model_name: str, model_info: dict[str, Any]) -> Any:
        if self._loaded_model is not None and self._loaded_model_name == model_name:
            return self._loaded_model
        model_path = Path(str(model_info.get("path") or ""))
        if not model_path.is_absolute():
            model_path = self.model_dir / model_path
        if not model_path.exists():
            raise ModelInferenceError(
                f"Approved model artifact is missing: {model_path}"
            )
        try:
            import joblib
        except (
            ImportError
        ) as exc:  # pragma: no cover - depends on deployment environment
            raise ModelInferenceError(
                "joblib is required for deployment model inference"
            ) from exc
        self._loaded_model = joblib.load(model_path)
        self._loaded_model_name = model_name
        return self._loaded_model

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise ModelInferenceError(
                f"Required model metadata file is missing: {path}"
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ModelInferenceError(
                f"Model metadata is not valid JSON: {path}"
            ) from exc

    def _risk_signal(self, probability: float) -> str:
        if probability >= 0.65:
            return "risk_high"
        if probability >= 0.35:
            return "risk_medium"
        return "risk_low"

    def _confidence(
        self, *, risk_probability: float, feature_coverage: float, real_share: float
    ) -> float:
        directional_strength = abs(risk_probability - 0.5) * 2.0
        confidence = (
            0.45
            + (0.35 * feature_coverage)
            + (0.15 * directional_strength)
            + (0.05 * real_share)
        )
        return max(0.0, min(0.95, confidence))

    def _feature_warnings(self, feature_vector: SnapshotFeatureVector) -> list[str]:
        if not feature_vector.missing_features:
            return []
        preview = ", ".join(feature_vector.missing_features[:6])
        suffix = "" if len(feature_vector.missing_features) <= 6 else ", ..."
        return [f"Feature defaults used for: {preview}{suffix}"]

    def _clean_probability(self, probability: float) -> float:
        if math.isnan(probability) or math.isinf(probability):
            raise ModelInferenceError("Model returned a non-finite probability")
        return max(0.0, min(1.0, probability))
