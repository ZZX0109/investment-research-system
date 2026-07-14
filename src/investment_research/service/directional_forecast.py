from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from investment_research.domain.market_models import DirectionalForecast
from investment_research.repository.sqlite import SQLiteUnitOfWork

DEFAULT_MANIFEST = Path(__file__).resolve().parents[3] / "output/models/directional_model_manifest.json"


class DirectionalForecastResponse(BaseModel):
    status: str
    forecast: DirectionalForecast | None = None
    gating_reasons: list[str] = Field(default_factory=list)


class DirectionalForecastService:
    def __init__(self, uow: SQLiteUnitOfWork, manifest_path: Path = DEFAULT_MANIFEST) -> None:
        self.uow, self.manifest_path = uow, manifest_path

    def for_run(self, run_id: str) -> DirectionalForecastResponse:
        item = self.uow.market_observations.directional_for_run(run_id)
        manifest = self._manifest()
        if not manifest or manifest.get("status") != "approved":
            return DirectionalForecastResponse(status="research_only", gating_reasons=["Direction model has not passed the independent approval gate"])
        if item is None or item.status != "approved":
            return DirectionalForecastResponse(status="unavailable", gating_reasons=["No approved directional forecast is frozen for this run"])
        return DirectionalForecastResponse(status="approved", forecast=item)

    def _manifest(self) -> dict:
        try: return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError): return {}
