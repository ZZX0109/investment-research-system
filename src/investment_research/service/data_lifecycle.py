from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from investment_research.domain.base import utc_now
from investment_research.domain.enums import DataMode
from investment_research.domain.enums import EvidenceType
from investment_research.domain.models import Evidence, PriceSeries


@dataclass(frozen=True)
class FreshnessWindow:
    price_max_age: timedelta
    evidence_max_age: timedelta


@dataclass(frozen=True)
class FreshnessAssessment:
    status: str
    as_of: datetime | None
    age_hours: float | None
    refresh_after: datetime | None
    reasons: list[str]


@dataclass(frozen=True)
class LifecycleAssessment:
    price: FreshnessAssessment
    evidence: FreshnessAssessment
    refresh_recommendation: str
    stale_reasons: list[str]
    evidence_citation_ids: list[str]


class AnalysisLifecycleService:
    def __init__(self) -> None:
        self._windows = {
            DataMode.DEMO: FreshnessWindow(price_max_age=timedelta(days=30), evidence_max_age=timedelta(days=30)),
            DataMode.SANDBOX: FreshnessWindow(price_max_age=timedelta(days=14), evidence_max_age=timedelta(days=14)),
            DataMode.REAL: FreshnessWindow(price_max_age=timedelta(days=7), evidence_max_age=timedelta(days=3)),
        }

    def assess(
        self,
        *,
        data_mode: DataMode,
        price_series: list[PriceSeries],
        evidence: list[Evidence],
    ) -> LifecycleAssessment:
        window = self._windows[data_mode]
        price_assessment = self._assess_price(price_series, max_age=window.price_max_age)
        evidence_assessment = self._assess_evidence(evidence, max_age=window.evidence_max_age)
        stale_reasons = [*price_assessment.reasons, *evidence_assessment.reasons]

        if "missing" in {price_assessment.status, evidence_assessment.status}:
            refresh = "block_until_inputs_recovered"
        elif "stale" in {price_assessment.status, evidence_assessment.status}:
            refresh = "refresh_recommended_before_action"
        else:
            refresh = "fresh_enough_for_current_mode"

        return LifecycleAssessment(
            price=price_assessment,
            evidence=evidence_assessment,
            refresh_recommendation=refresh,
            stale_reasons=stale_reasons,
            evidence_citation_ids=[str(item.id) for item in evidence],
        )

    def _assess_price(self, price_series: list[PriceSeries], *, max_age: timedelta) -> FreshnessAssessment:
        latest_timestamp = None
        for series in price_series:
            if not series.points:
                continue
            candidate = series.points[-1].timestamp
            if latest_timestamp is None or candidate > latest_timestamp:
                latest_timestamp = candidate
        if latest_timestamp is None:
            return FreshnessAssessment(
                status="missing",
                as_of=None,
                age_hours=None,
                refresh_after=None,
                reasons=["Price inputs are missing and should be refreshed before analysis."],
            )
        return self._build_assessment(
            as_of=latest_timestamp,
            max_age=max_age,
            stale_reason=f"Price inputs are older than the allowed freshness window of {int(max_age.total_seconds() // 86400)} days.",
        )

    def _assess_evidence(self, evidence: list[Evidence], *, max_age: timedelta) -> FreshnessAssessment:
        if not evidence:
            return FreshnessAssessment(
                status="missing",
                as_of=None,
                age_hours=None,
                refresh_after=None,
                reasons=["Evidence inputs are missing and should be refreshed before analysis."],
            )
        freshest_item = max(evidence, key=lambda item: item.collected_at)
        latest_timestamp = freshest_item.collected_at
        evidence_max_age = self._max_age_for_evidence(freshest_item, fallback=max_age)
        return self._build_assessment(
            as_of=latest_timestamp,
            max_age=evidence_max_age,
            stale_reason=f"Evidence inputs are older than the allowed freshness window of {int(evidence_max_age.total_seconds() // 86400)} days.",
        )

    def _max_age_for_evidence(self, evidence: Evidence, *, fallback: timedelta) -> timedelta:
        if evidence.evidence_type in {EvidenceType.NEWS, EvidenceType.MODEL_OUTPUT}:
            return timedelta(days=1)
        if evidence.evidence_type in {EvidenceType.FILING, EvidenceType.RESEARCH_NOTE, EvidenceType.MANUAL_NOTE}:
            return timedelta(days=7)
        if evidence.evidence_type == EvidenceType.MARKET_DATA:
            return timedelta(days=1)
        return fallback

    def _build_assessment(self, *, as_of: datetime, max_age: timedelta, stale_reason: str) -> FreshnessAssessment:
        age = utc_now() - as_of
        refresh_after = as_of + max_age
        if age > max_age:
            return FreshnessAssessment(
                status="stale",
                as_of=as_of,
                age_hours=round(age.total_seconds() / 3600, 2),
                refresh_after=refresh_after,
                reasons=[stale_reason],
            )
        return FreshnessAssessment(
            status="fresh",
            as_of=as_of,
            age_hours=round(age.total_seconds() / 3600, 2),
            refresh_after=refresh_after,
            reasons=[],
        )
