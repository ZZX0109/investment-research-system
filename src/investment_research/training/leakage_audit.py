from __future__ import annotations

from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Iterable

from pydantic import BaseModel, Field

from investment_research.domain.pit import (
    CorporateActionRevision,
    HistoricalUniverseMembership,
    StandardEventRevision,
)
from investment_research.training.models import PointInTimeEvent, PreparedPriceBar


class LeakageSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LeakageFinding(BaseModel):
    code: str
    severity: LeakageSeverity
    dataset: str
    record_key: str
    detail: str


class LeakageAuditReport(BaseModel):
    training_run_id: str
    decision_time: datetime
    generated_at: datetime
    checks: list[str] = Field(default_factory=list)
    findings: list[LeakageFinding] = Field(default_factory=list)
    report_hash: str = ""

    @property
    def error_count(self) -> int:
        return sum(item.severity == LeakageSeverity.ERROR for item in self.findings)

    @property
    def publishable(self) -> bool:
        return self.error_count == 0

    def verify_hash(self) -> bool:
        return self.report_hash == _report_hash(
            self.model_dump(mode="json", exclude={"report_hash"})
        )


def audit_point_in_time_inputs(
    *,
    training_run_id: str,
    decision_time: datetime,
    generated_at: datetime,
    bars: Iterable[PreparedPriceBar] = (),
    events: Iterable[PointInTimeEvent | StandardEventRevision] = (),
    universe: Iterable[HistoricalUniverseMembership] = (),
    corporate_actions: Iterable[CorporateActionRevision] = (),
    feature_names: Iterable[str] = (),
    label_names: Iterable[str] = (),
) -> LeakageAuditReport:
    if decision_time.tzinfo is None or generated_at.tzinfo is None:
        raise ValueError("audit times must be timezone-aware")
    findings: list[LeakageFinding] = []

    for bar in bars:
        available_at = bar.available_at or bar.published_at
        key = f"{bar.symbol}:{bar.trade_date}:r{bar.revision}"
        if available_at > decision_time:
            findings.append(
                _error(
                    "future_price_bar",
                    "price",
                    key,
                    "bar available_at is after decision_time",
                )
            )
        if bar.available_at is None:
            findings.append(
                _error(
                    "unproven_price_availability",
                    "price",
                    key,
                    "available_at is absent; published_at fallback is not publishable PIT evidence",
                )
            )

    by_event: dict[str, list[StandardEventRevision]] = {}
    for event in events:
        available_at = event.available_at or event.published_at
        key = getattr(
            event, "logical_event_id", f"{event.symbol}:{event.event_time.isoformat()}"
        )
        if available_at > decision_time:
            findings.append(
                _error(
                    "future_event_revision",
                    "event",
                    key,
                    "event revision was not visible at the decision",
                )
            )
        if isinstance(event, StandardEventRevision):
            by_event.setdefault(event.logical_event_id, []).append(event)
    for logical_id, revisions in by_event.items():
        visible = [item for item in revisions if item.available_at <= decision_time]
        if visible and max(visible, key=lambda item: item.revision).revision != max(
            item.revision for item in visible
        ):
            findings.append(
                _error(
                    "event_revision_order",
                    "event",
                    logical_id,
                    "visible event revision ordering is inconsistent",
                )
            )

    for item in universe:
        key = f"{item.market}:{item.symbol}:r{item.revision}"
        if item.available_at > decision_time:
            findings.append(
                _error(
                    "future_universe_membership",
                    "universe",
                    key,
                    "historical membership was learned after the decision",
                )
            )
        if item.effective_from > decision_time:
            findings.append(
                _error(
                    "future_universe_effective_date",
                    "universe",
                    key,
                    "future membership entered the historical universe",
                )
            )

    for action in corporate_actions:
        key = f"{action.market}:{action.symbol}:{action.ex_date}:r{action.revision}"
        if action.available_at > decision_time:
            findings.append(
                _error(
                    "future_adjustment_revision",
                    "corporate_action",
                    key,
                    "later corporate-action revision would rewrite history",
                )
            )

    overlap = sorted(set(feature_names) & set(label_names))
    for name in overlap:
        findings.append(
            _error(
                "label_in_feature_contract",
                "feature",
                name,
                "a label field is present in the feature contract",
            )
        )

    report = LeakageAuditReport(
        training_run_id=training_run_id,
        decision_time=decision_time,
        generated_at=generated_at,
        checks=[
            "available_at_lte_decision_time",
            "event_revision_as_of",
            "corporate_action_revision_as_of",
            "historical_universe_as_of",
            "label_feature_separation",
        ],
        findings=findings,
    )
    report.report_hash = _report_hash(
        report.model_dump(mode="json", exclude={"report_hash"})
    )
    return report


def require_publishable_leakage_report(report: LeakageAuditReport) -> None:
    if not report.verify_hash():
        raise ValueError("leakage report hash mismatch")
    if not report.publishable:
        raise ValueError(
            f"leakage audit contains {report.error_count} ERROR finding(s)"
        )


def _error(code: str, dataset: str, key: str, detail: str) -> LeakageFinding:
    return LeakageFinding(
        code=code,
        severity=LeakageSeverity.ERROR,
        dataset=dataset,
        record_key=key,
        detail=detail,
    )


def _report_hash(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
