from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field

from investment_research.domain.models import User
from investment_research.repository.sqlite import SQLiteUnitOfWork


class ReviewGroup(BaseModel):
    key: str
    observation_count: int
    evaluated_count: int
    risk_hit_rate: float | None = Field(default=None, ge=0, le=1)
    abstention_rate: float = Field(ge=0, le=1)
    average_return_5d: float | None = None
    average_return_20d: float | None = None
    average_return_60d: float | None = None
    error_categories: dict[str, int] = Field(default_factory=dict)


class ResearchReviewSummary(BaseModel):
    group_by: str
    groups: list[ReviewGroup]


class ResearchReviewService:
    def __init__(self, uow: SQLiteUnitOfWork) -> None:
        self.uow = uow

    def summarize(self, *, user: User, group_by: Literal["month", "model", "industry", "symbol", "market_state"]) -> ResearchReviewSummary:
        grouped = defaultdict(list)
        for item in self.uow.paper_observations.list_all():
            run = self.uow.analysis_runs.get(str(item.analysis_run_id))
            if run is None or run.triggered_by != user.auth_subject:
                continue
            asset = self.uow.assets.get(str(item.asset_id))
            if group_by == "month":
                key = item.prediction_as_of.strftime("%Y-%m")
            elif group_by == "model":
                key = next(iter(item.model_versions.values()), "unavailable")
            elif group_by == "industry":
                master = None if asset is None else self.uow.trusted_market.security_as_of(asset.ticker, item.prediction_as_of)
                key = "unknown" if master is None else (master[1].industry if master[1] and master[1].industry else master[0].industry or "unknown")
            elif group_by == "symbol":
                key = "unknown" if asset is None else asset.ticker
            else:
                key = "abstained" if item.abstained else "risk_alert" if (item.predicted_risk or 0) >= 0.5 else "normal"
            grouped[key].append(item)
        groups: list[ReviewGroup] = []
        for key, items in sorted(grouped.items()):
            settled = [item for item in items if item.outcome in {"risk_hit", "risk_miss"}]
            errors = defaultdict(int)
            for item in items:
                errors[item.error_category] += 1
            groups.append(ReviewGroup(
                key=key,
                observation_count=len(items),
                evaluated_count=len(settled),
                risk_hit_rate=None if not settled else sum(item.outcome == "risk_hit" for item in settled) / len(settled),
                abstention_rate=sum(item.abstained for item in items) / len(items),
                average_return_5d=self._average(items, "5"),
                average_return_20d=self._average(items, "20"),
                average_return_60d=self._average(items, "60"),
                error_categories=dict(errors),
            ))
        return ResearchReviewSummary(group_by=group_by, groups=groups)

    @staticmethod
    def _average(items, key: str) -> float | None:
        values = [item.milestones[key].realized_return for item in items if key in item.milestones]
        return None if not values else sum(values) / len(values)
